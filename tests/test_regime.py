from lib.regime import _allocation_trigger_signal, _classify, _signal_spy_drawdown


def test_allocation_trigger_stays_max_conviction_before_five_percent_drawdown():
    signal = _allocation_trigger_signal(-4.9)

    assert signal["verdict"] == "Stay Max Conviction"
    assert _classify(score=-6, spy_drawdown=-4.9)["tag"] == "s1s2"


def test_allocation_trigger_moves_to_confident_bull_at_five_percent_drawdown():
    signal = _allocation_trigger_signal(-5.0)
    classification = _classify(score=4, spy_drawdown=-5.0)

    assert signal["verdict"] == "Move to Confident Bull"
    assert classification["tag"] == "s2"
    assert "Confident Bull" in classification["guidance"]


def test_allocation_trigger_moves_to_bubble_pop_at_ten_percent_drawdown():
    signal = _allocation_trigger_signal(-10.0)
    classification = _classify(score=4, spy_drawdown=-10.0)

    assert signal["verdict"] == "Move to Bubble Pop (S3)"
    assert classification["tag"] == "s3"
    assert "Bubble Pop" in classification["guidance"]


def test_spy_drawdown_signal_names_strategy_thresholds():
    five_percent = _signal_spy_drawdown([100.0, 95.0])
    ten_percent = _signal_spy_drawdown([100.0, 90.0])

    assert five_percent["verdict"] == "Confident Bull trigger (-5%)"
    assert ten_percent["verdict"] == "Bubble Pop trigger (-10%)"
