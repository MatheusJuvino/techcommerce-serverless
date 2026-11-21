"""Lê o template AWS SAM e extrai funções, rotas, regras, agendamentos e recursos.

Usar o template como fonte única garante que a simulação local siga exatamente as mesmas
rotas da API, padrões de eventos e políticas de retentativa que serão implantados na AWS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class CfnLoader(yaml.SafeLoader):
    pass


def _construct_intrinsic(loader: CfnLoader, tag_suffix: str, node: yaml.Node) -> dict:
    if isinstance(node, yaml.ScalarNode):
        value: Any = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    if tag_suffix == "Ref":
        return {"Ref": value}
    if tag_suffix == "GetAtt" and isinstance(value, str):
        value = value.split(".", 1)
    return {f"Fn::{tag_suffix}": value}


CfnLoader.add_multi_constructor("!", _construct_intrinsic)


@dataclass
class RuleDef:
    name: str
    pattern: dict
    retry_attempts: int


@dataclass
class ScheduleDef:
    name: str
    expression: str
    timezone: str
    input: str
    state: str


@dataclass
class FunctionDef:
    logical_id: str
    handler: str
    function_name: str
    async_retry_attempts: int = 2
    api_routes: list[tuple[str, str]] = field(default_factory=list)
    rules: list[RuleDef] = field(default_factory=list)
    schedules: list[ScheduleDef] = field(default_factory=list)


@dataclass
class TemplateModel:
    raw: dict
    parameters: dict[str, Any]
    functions: dict[str, FunctionDef]
    resources: dict[str, dict]
    global_env: dict[str, Any]


class Resolver:
    """Resolve funções intrínsecas simples (Ref, Sub, GetAtt) para valores locais."""

    def __init__(self, parameters: dict[str, Any], physical_ids: dict[str, str]):
        self.parameters = parameters
        self.physical_ids = physical_ids

    def resolve(self, value: Any) -> Any:
        if isinstance(value, dict) and len(value) == 1:
            (key, arg), = value.items()
            if key == "Ref":
                if arg in self.parameters:
                    return self.parameters[arg]
                return self.physical_ids.get(arg, arg)
            if key == "Fn::Sub":
                template = arg if isinstance(arg, str) else arg[0]
                return re.sub(r"\$\{([^}]+)\}", lambda m: str(self._sub_var(m.group(1))), template)
            if key == "Fn::GetAtt":
                return self.physical_ids.get(f"{arg[0]}.{arg[1]}", f"{arg[0]}.{arg[1]}")
        if isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        return value

    def _sub_var(self, name: str):
        if name in self.parameters:
            return self.parameters[name]
        if name == "AWS::Region":
            return "sa-east-1"
        if name == "AWS::AccountId":
            return "123456789012"
        return self.physical_ids.get(name, name)


def load_template(path: str | Path, overrides: dict[str, Any] | None = None) -> TemplateModel:
    raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=CfnLoader)  # noqa: S506 - loader seguro customizado
    parameters = {name: spec.get("Default") for name, spec in raw.get("Parameters", {}).items()}
    parameters.update(overrides or {})
    resolver = Resolver(parameters, {})
    resources = raw["Resources"]
    functions: dict[str, FunctionDef] = {}
    for logical_id, resource in resources.items():
        if resource["Type"] != "AWS::Serverless::Function":
            continue
        props = resource["Properties"]
        fn = FunctionDef(
            logical_id=logical_id,
            handler=props["Handler"],
            function_name=resolver.resolve(props.get("FunctionName", logical_id)),
            async_retry_attempts=props.get("EventInvokeConfig", {}).get("MaximumRetryAttempts", 2),
        )
        for event_name, event in (props.get("Events") or {}).items():
            event_props = event.get("Properties", {})
            if event["Type"] == "Api":
                fn.api_routes.append((event_props["Method"].upper(), event_props["Path"]))
            elif event["Type"] == "EventBridgeRule":
                fn.rules.append(
                    RuleDef(
                        name=resolver.resolve(event_props.get("RuleName", event_name)),
                        pattern=event_props["Pattern"],
                        retry_attempts=event_props.get("RetryPolicy", {}).get("MaximumRetryAttempts", 185),
                    )
                )
            elif event["Type"] in ("ScheduleV2", "Schedule"):
                fn.schedules.append(
                    ScheduleDef(
                        name=resolver.resolve(event_props.get("Name", event_name)),
                        expression=resolver.resolve(event_props.get("ScheduleExpression") or event_props.get("Schedule")),
                        timezone=resolver.resolve(event_props.get("ScheduleExpressionTimezone", "UTC")),
                        input=event_props.get("Input", "{}"),
                        state=resolver.resolve(event_props.get("State", "ENABLED")),
                    )
                )
        functions[logical_id] = fn
    global_env = raw.get("Globals", {}).get("Function", {}).get("Environment", {}).get("Variables", {})
    return TemplateModel(raw=raw, parameters=parameters, functions=functions, resources=resources, global_env=global_env)
