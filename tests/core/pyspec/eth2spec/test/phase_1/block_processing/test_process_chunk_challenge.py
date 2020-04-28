from eth2spec.test.helpers.custody import (
    get_valid_chunk_challenge,
    get_valid_custody_chunk_response,
    get_custody_test_vector,
    get_custody_merkle_root,
    get_shard_transition,
)
from eth2spec.test.helpers.attestations import (
    get_valid_on_time_attestation,
)
from eth2spec.test.helpers.state import transition_to
from eth2spec.utils.ssz.ssz_impl import hash_tree_root
from eth2spec.test.context import (
    with_all_phases_except,
    spec_state_test,
    expect_assertion_error,
)
from eth2spec.test.phase_0.block_processing.test_process_attestation import run_attestation_processing


def run_chunk_challenge_processing(spec, state, custody_chunk_challenge, valid=True):
    """
    Run ``process_chunk_challenge``, yielding:
      - pre-state ('pre')
      - CustodyBitChallenge ('custody_chunk_challenge')
      - post-state ('post').
    If ``valid == False``, run expecting ``AssertionError``
    """
    yield 'pre', state
    yield 'custody_chunk_challenge', custody_chunk_challenge

    if not valid:
        expect_assertion_error(lambda: spec.custody_chunk_challenge(state, custody_chunk_challenge))
        yield 'post', None
        return

    spec.process_chunk_challenge(state, custody_chunk_challenge)

    assert state.custody_chunk_challenge_records[state.custody_chunk_challenge_index - 1].responder_index == \
        custody_chunk_challenge.responder_index
    assert state.custody_chunk_challenge_records[state.custody_chunk_challenge_index - 1].chunk_index == \
        custody_chunk_challenge.chunk_index

    yield 'post', state


def run_custody_chunk_response_processing(spec, state, custody_response, valid=True):
    """
    Run ``process_chunk_challenge_response``, yielding:
      - pre-state ('pre')
      - CustodyResponse ('custody_response')
      - post-state ('post').
    If ``valid == False``, run expecting ``AssertionError``
    """
    yield 'pre', state
    yield 'custody_response', custody_response

    if not valid:
        expect_assertion_error(lambda: spec.process_custody_response(state, custody_response))
        yield 'post', None
        return

    spec.process_chunk_challenge_response(state, custody_response)

    assert state.custody_chunk_challenge_records[custody_response.challenge_index] == spec.CustodyChunkChallengeRecord()

    yield 'post', state


@with_all_phases_except(['phase0'])
@spec_state_test
def test_challenge_appended(spec, state):
    transition_to(spec, state, state.slot + 1)
    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_chunks = (shard_transition.shard_block_lengths[data_index] + spec.BYTES_PER_CUSTODY_CHUNK - 1) // spec.BYTES_PER_CUSTODY_CHUNK
    test_vector = get_custody_test_vector(shard_transition.shard_block_lengths[data_index])
    shard_root = get_custody_merkle_root(test_vector)

    transition_to(spec, state, state.slot + spec.MIN_ATTESTATION_INCLUSION_DELAY)

    _, _, _ = run_attestation_processing(spec, state, attestation)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * spec.EPOCHS_PER_CUSTODY_PERIOD)

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    yield from run_chunk_challenge_processing(spec, state, challenge)


@with_all_phases_except(['phase0'])
@spec_state_test
def test_multiple_epochs_custody(spec, state):
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * 3)

    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_to(spec, state, state.slot + spec.MIN_ATTESTATION_INCLUSION_DELAY)

    _, _, _ = run_attestation_processing(spec, state, attestation)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * (spec.EPOCHS_PER_CUSTODY_PERIOD - 1))

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    yield from run_chunk_challenge_processing(spec, state, challenge)


@with_all_phases_except(['phase0'])
@spec_state_test
def test_many_epochs_custody(spec, state):
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * 100)

    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_to(spec, state, state.slot + spec.MIN_ATTESTATION_INCLUSION_DELAY)

    _, _, _ = run_attestation_processing(spec, state, attestation)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * (spec.EPOCHS_PER_CUSTODY_PERIOD - 1))

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    yield from run_chunk_challenge_processing(spec, state, challenge)


@with_all_phases_except(['phase0'])
@spec_state_test
def test_off_chain_attestation(spec, state):
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH)

    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * (spec.EPOCHS_PER_CUSTODY_PERIOD - 1))

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    yield from run_chunk_challenge_processing(spec, state, challenge)


@with_all_phases_except(['phase0'])
@spec_state_test
def test_custody_response(spec, state):
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH)

    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_to(spec, state, state.slot + spec.MIN_ATTESTATION_INCLUSION_DELAY)

    _, _, _ = run_attestation_processing(spec, state, attestation)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * (spec.EPOCHS_PER_CUSTODY_PERIOD - 1))

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    _, _, _ = run_chunk_challenge_processing(spec, state, challenge)

    chunk_challenge_index = state.custody_chunk_challenge_index - 1

    custody_response = get_valid_custody_chunk_response(spec, state, challenge, 2**15 // 3, chunk_challenge_index)

    yield from run_custody_chunk_response_processing(spec, state, custody_response)


@with_all_phases_except(['phase0'])
@spec_state_test
def test_custody_response_multiple_epochs(spec, state):
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * 3)

    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_to(spec, state, state.slot + spec.MIN_ATTESTATION_INCLUSION_DELAY)

    _, _, _ = run_attestation_processing(spec, state, attestation)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * (spec.EPOCHS_PER_CUSTODY_PERIOD - 1))

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    _, _, _ = run_chunk_challenge_processing(spec, state, challenge)

    chunk_challenge_index = state.custody_chunk_challenge_index - 1

    custody_response = get_valid_custody_chunk_response(spec, state, challenge, 2**15 // 3, chunk_challenge_index)

    yield from run_custody_chunk_response_processing(spec, state, custody_response)


@with_all_phases_except(['phase0'])
@spec_state_test
def test_custody_response_many_epochs(spec, state):
    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * 100)

    shard = 0
    offset_slots = spec.get_offset_slots(state, shard)
    shard_transition = get_shard_transition(spec, state.slot, [2**15 // 3] * len(offset_slots))
    data_index = 0
    attestation = get_valid_on_time_attestation(spec, state, index=shard, signed=True, shard_transition=shard_transition)

    transition_to(spec, state, state.slot + spec.MIN_ATTESTATION_INCLUSION_DELAY)

    _, _, _ = run_attestation_processing(spec, state, attestation)

    transition_to(spec, state, state.slot + spec.SLOTS_PER_EPOCH * (spec.EPOCHS_PER_CUSTODY_PERIOD - 1))

    challenge = get_valid_chunk_challenge(spec, state, attestation, shard_transition)

    _, _, _ = run_chunk_challenge_processing(spec, state, challenge)

    chunk_challenge_index = state.custody_chunk_challenge_index - 1

    custody_response = get_valid_custody_chunk_response(spec, state, challenge, 2**15 // 3, chunk_challenge_index)

    yield from run_custody_chunk_response_processing(spec, state, custody_response)