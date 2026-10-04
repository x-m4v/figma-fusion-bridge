from ffbridge.ascii_writer import Tool, Point


def test_loader_serializes_media_as_clip_record_not_input():
    text = Tool('Loader', 'Photo', {'Clip': '/tmp/photo.png', 'Loop': 1}).render('')
    assert 'Clips = { Clip {' in text
    assert 'Filename = "/tmp/photo.png"' in text
    assert 'FormatID = "PNGFormat"' in text
    assert 'Clip = Input' not in text


def test_point_input_uses_native_positional_pair():
    text = Tool('Transform', 'Position', {'Center': Point(0.25, 0.75)}).render('')
    assert 'Center = Input { Value = { 0.25, 0.75 }' in text
    assert 'Point {' not in text
