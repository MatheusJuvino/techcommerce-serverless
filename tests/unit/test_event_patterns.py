from local_runtime.event_pattern import matches

EVENT = {"source": "techcommerce.orders", "detail-type": "OrderReceived",
         "detail": {"data": {"total": 150, "paymentMethod": "PIX"}, "metadata": {"eventId": "1"}}}


def test_exact_and_nested_matching():
    assert matches({"source": ["techcommerce.orders"], "detail-type": ["OrderReceived"]}, EVENT)
    assert matches({"detail": {"data": {"paymentMethod": ["PIX", "BOLETO"]}}}, EVENT)
    assert not matches({"source": ["techcommerce.payments"]}, EVENT)
    assert not matches({"detail": {"data": {"paymentMethod": ["BOLETO"]}}}, EVENT)


def test_content_filters():
    assert matches({"detail-type": [{"prefix": "Order"}]}, EVENT)
    assert matches({"source": [{"anything-but": "techcommerce.payments"}]}, EVENT)
    assert matches({"detail": {"data": {"coupon": [{"exists": False}]}}}, EVENT)
    assert matches({"detail": {"data": {"total": [{"numeric": [">", 100, "<=", 200]}]}}}, EVENT)
    assert not matches({"detail": {"data": {"total": [{"numeric": [">", 500]}]}}}, EVENT)
