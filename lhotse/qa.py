from typing import Any, Callable, Dict

from math import isclose

from lhotse import CutSet, FeatureSet, Features, Recording, RecordingSet, SupervisionSegment, SupervisionSet
from lhotse.cut import AnyCut, MixedCut, PaddingCut

_VALIDATORS: Dict[str, Callable] = {}


def validate(obj: Any, read_data: bool = False):
    """
    Validate a Lhotse manifest object.
    It checks for conditions such as positive duration, matching channels, ids, etc.
    It raises AssertionError when it finds some mismatch.

    Optionally it can load the audio/feature data from disk and inspect whether the
    num samples/frames/features declared in the manifests are matching the actual data.

    This function determines the passed object's type and automatically calls
    the proper validator for that object.
    """
    obj_type = type(obj)
    valid = _VALIDATORS.get(obj_type)
    if valid is None:
        raise ValueError(
            f"Object of unknown type passed to validate() (T = {obj_type}, known types = {list(_VALIDATORS)}"
        )
    valid(obj, read_data=read_data)


def register_validator(fn):
    """
    Decorator registers the function to be invoked inside ``validate()``
    when the first argument's type is matching.
    """
    # Check the first function argument's type
    first_arg_type = next(iter(fn.__annotations__.values()))
    # Register the function to be called when an object of that type is passed to validate()
    _VALIDATORS[first_arg_type] = fn
    return fn


@register_validator
def validate_recording(r: Recording, read_data: bool = False) -> None:
    assert r.duration > 0, f'Recording {r.id}: duration has to be greater than 0 (is {r.duration})'
    expected_duration = r.num_samples / r.sampling_rate
    assert r.num_channels > 0, f'Recording {r.id}: no channels available'
    assert isclose(expected_duration, r.duration), \
        f'Recording {r.id}: mismatched declared duration ({r.duration}) with ' \
        f'num_samples / sampling_rate ({expected_duration}).'
    if read_data:
        samples = r.load_audio()
        n_ch, n_s = samples.shape
        assert r.num_channels == n_ch, f'Recording {r.id}: expected {r.num_channels} channels, got {n_ch}'
        assert r.num_samples == n_s, f'Recording {r.id}: expected {r.num_samples} samples, got {n_s}'


@register_validator
def validate_supervision(s: SupervisionSegment, **kwargs) -> None:
    assert s.duration > 0, f'Supervision {s.id}: duration has to be greater than 0 (is {s.duration})'


@register_validator
def validate_features(f: Features, read_data: bool = False) -> None:
    assert f.start >= 0, \
        f'Features: start has to be greater than 0 (is {f.start})'
    assert f.duration > 0, \
        f'Features: duration has to be greater than 0 (is {f.duration})'
    assert f.num_frames > 0, \
        f'Features: num_frames has to be greater than 0 (is {f.num_frames})'
    assert f.num_features > 0, \
        f'Features: num_features has to be greater than 0 (is {f.num_features})'
    assert f.sampling_rate > 0, \
        f'Features: sampling_rate has to be greater than 0 (is {f.sampling_rate})'
    if read_data:
        feats = f.load()
        n_fr, n_ft = feats.shape
        assert f.num_frames == n_fr, f'Features: expected num_frames: {f.num_frames}, actual: {n_fr}'
        assert f.num_features == n_ft, f'Features: expected num_features: {f.num_features}, actual: {n_ft}'


@register_validator
def validate_cut(c: AnyCut, read_data: bool = False) -> None:
    # Validate MixedCut
    if isinstance(c, MixedCut):
        assert len(c.tracks) > 0, f'Cut {c.id}: Mixed cut must have at least one track.'
        for idx, track in enumerate(c.tracks):
            validate_cut(track.cut, read_data=read_data)
            assert track.offset >= 0, f'Cut: {c.id}: track {idx} has a negative offset.'
        return

    # Validate Cut and PaddingCut
    assert c.start >= 0, f'Cut {c.id}: start must be 0 or greater (got {c.start})'
    assert c.duration > 0, f'Cut {c.id}: duration must be greater than 0 (got {c.duration})'
    assert c.sampling_rate > 0, f'Cut {c.id}: sampling_rate must be greater than 0 (got {c.sampling_rate})'
    assert c.has_features or c.has_recording, f'Cut {c.id}: must have either Features or Recording attached.'

    # The rest pertains only to regular Cuts
    if isinstance(c, PaddingCut):
        return

    # Conditions related to features
    if c.has_features:
        validate_features(c.features)
        assert c.channel == c.features.channels
        if read_data:
            # We are not passing "read_data" to "validate_features" to avoid loading feats twice;
            # we'll just validate the subset of the features relevant for the cut.
            feats = c.load_features()
            n_fr, n_ft = feats.shape
            assert c.num_frames == n_fr, f'Cut {c.id}: expected num_frames: {c.num_frames}, actual: {n_fr}'
            assert c.num_features == n_ft, f'Cut {c.id}: expected num_features: {c.num_features}, actual: {n_ft}'

    # Conditions related to recording
    if c.has_recording:
        validate_recording(c.recording)
        assert c.channel in c.recording.channel_ids
        if read_data:
            # We are not passing "read_data" to "validate_recording" to avoid loading audio twice;
            # we'll just validate the subset of the recording relevant for the cut.
            samples = c.load_audio()
            assert c.num_samples == samples.shape[1], \
                f'Cut {c.id}: expected {c.num_samples} samples, got {samples.shape[1]}'

    # Conditions related to supervisions
    for s in c.supervisions:
        validate_supervision(s)
        assert s.recording_id == c.recording_id
        assert s.channel == c.channel


@register_validator
def validate_recording_set(recordings: RecordingSet, read_data: bool = False) -> None:
    first = next(iter(recordings))
    sampling_rate = first.sampling_rate
    for r in recordings:
        validate_recording(r, read_data=read_data)
        assert r.sampling_rate == sampling_rate


@register_validator
def validate_supervision_set(supervisions: SupervisionSet, **kwargs) -> None:
    for s in supervisions:
        validate_supervision(s)


@register_validator
def validate_feature_set(features: FeatureSet, read_data: bool = False) -> None:
    first = next(iter(features))
    sampling_rate = first.sampling_rate
    num_features = first.num_features
    features_type = first.features_type
    for f in features:
        validate_features(f, read_data=read_data)
        assert f.sampling_rate == sampling_rate
        assert f.num_features == num_features
        assert f.type == features_type


@register_validator
def validate_cut_set(cuts: CutSet, read_data: bool = False) -> None:
    for c in cuts:
        validate_cut(c, read_data=read_data)
