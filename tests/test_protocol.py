from neurogrip.protocol import SensorFrame, fmt_buzzer, fmt_led, fmt_servo, parse_sensor_line


def test_parse_valid():
    f = parse_sensor_line("S,1200,410,395,12,-8,1003\n")
    assert f == SensorFrame(1200, 410, 395, 12, -8, 1003)


def test_parse_garbage_returns_none():
    for bad in ["", "S,1,2", "X,1,2,3,4,5,6", "S,a,b,c,d,e,f", "\x00\xffS,1"]:
        assert parse_sensor_line(bad) is None


def test_fmt_servo_clamps():
    assert fmt_servo(-5, 90, 200, 45, 161) == "A,0,90,160,45,160\n"


def test_fmt_led_and_buzzer():
    assert fmt_led("G") == "L,G\n"
    assert fmt_buzzer(880, 120) == "B,880,120\n"
