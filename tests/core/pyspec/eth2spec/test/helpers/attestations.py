from lru import LRU

from typing import List

from eth2spec.test.context import expect_assertion_error, PHASE0, PHASE1
from eth2spec.test.helpers.state import state_transition_and_sign_block, next_epoch, next_slot, transition_to
from eth2spec.test.helpers.block import build_empty_block_for_next_slot
from eth2spec.test.helpers.keys import privkeys
from eth2spec.utils import bls
from eth2spec.utils.ssz.ssz_typing import Bitlist
from eth2spec.test.helpers.custody import get_custody_test_vector


def run_attestation_processing(spec, state, attestation, valid=True):
    """
    Run ``process_attestation``, yielding:
      - pre-state ('pre')
      - attestation ('attestation')
      - post-state ('post').
    If ``valid == False``, run expecting ``AssertionError``
    """
    # yield pre-state
    yield 'pre', state

    yield 'attestation', attestation

    # If the attestation is invalid, processing is aborted, and there is no post-state.
    if not valid:
        expect_assertion_error(lambda: spec.process_attestation(state, attestation))
        yield 'post', None
        return

    current_epoch_count = len(state.current_epoch_attestations)
    previous_epoch_count = len(state.previous_epoch_attestations)

    # process attestation
    spec.process_attestation(state, attestation)

    # Make sure the attestation has been processed
    if attestation.data.target.epoch == spec.get_current_epoch(state):
        assert len(state.current_epoch_attestations) == current_epoch_count + 1
    else:
        assert len(state.previous_epoch_attestations) == previous_epoch_count + 1

    # yield post-state
    yield 'post', state


def build_attestation_data(spec, state, slot, index, shard_transition=None, on_time=True):
    assert state.slot >= slot

    if slot == state.slot:
        block_root = build_empty_block_for_next_slot(spec, state).parent_root
    else:
        block_root = spec.get_block_root_at_slot(state, slot)

    current_epoch_start_slot = spec.compute_start_slot_at_epoch(spec.get_current_epoch(state))
    if slot < current_epoch_start_slot:
        epoch_boundary_root = spec.get_block_root(state, spec.get_previous_epoch(state))
    elif slot == current_epoch_start_slot:
        epoch_boundary_root = block_root
    else:
        epoch_boundary_root = spec.get_block_root(state, spec.get_current_epoch(state))

    if slot < current_epoch_start_slot:
        source_epoch = state.previous_justified_checkpoint.epoch
        source_root = state.previous_justified_checkpoint.root
    else:
        source_epoch = state.current_justified_checkpoint.epoch
        source_root = state.current_justified_checkpoint.root

    attestation_data = spec.AttestationData(
        slot=slot,
        index=index,
        beacon_block_root=block_root,
        source=spec.Checkpoint(epoch=source_epoch, root=source_root),
        target=spec.Checkpoint(epoch=spec.compute_epoch_at_slot(slot), root=epoch_boundary_root),
    )

    if spec.fork == PHASE1:
        if shard_transition is not None:
            lastest_shard_data_root_index = len(shard_transition.shard_data_roots) - 1
            attestation_data.head_shard_root = shard_transition.shard_data_roots[lastest_shard_data_root_index]
            attestation_data.shard_transition_root = shard_transition.hash_tree_root()
        else:
            # No shard transition
            shard = spec.get_shard(state, spec.Attestation(data=attestation_data))
            if on_time:
                temp_state = state.copy()
                next_slot(spec, temp_state)
                shard_transition = spec.get_shard_transition(temp_state, shard, [])
                lastest_shard_data_root_index = len(shard_transition.shard_data_roots) - 1
                attestation_data.head_shard_root = shard_transition.shard_data_roots[lastest_shard_data_root_index]
                attestation_data.shard_transition_root = shard_transition.hash_tree_root()
            else:
                attestation_data.head_shard_root = state.shard_states[shard].transition_digest
                attestation_data.shard_transition_root = spec.Root()
    return attestation_data


def convert_to_valid_on_time_attestation(spec, state, attestation, signed=False, shard_transition=None,
                                         valid_custody_bits=None):
    shard = spec.get_shard(state, attestation)
    offset_slots = spec.compute_offset_slots(spec.get_latest_slot_for_shard(state, shard), state.slot + 1)

    if valid_custody_bits is not None:
        beacon_committee = spec.get_beacon_committee(
            state,
            attestation.data.slot,
            attestation.data.index,
        )
        custody_secrets = [None for i in beacon_committee]
        for i in range(len(beacon_committee)):
            period = spec.get_custody_period_for_validator(beacon_committee[i], attestation.data.target.epoch)
            epoch_to_sign = spec.get_randao_epoch_for_custody_period(period, beacon_committee[i])
            domain = spec.get_domain(state, spec.DOMAIN_RANDAO, epoch_to_sign)
            signing_root = spec.compute_signing_root(spec.Epoch(epoch_to_sign), domain)
            custody_secrets[i] = bls.Sign(privkeys[beacon_committee[i]], signing_root)

    for i, offset_slot in enumerate(offset_slots):
        attestation.custody_bits_blocks.append(
            Bitlist[spec.MAX_VALIDATORS_PER_COMMITTEE]([0 for _ in attestation.aggregation_bits])
        )
        if valid_custody_bits is not None:
            test_vector = get_custody_test_vector(shard_transition.shard_block_lengths[i])
            for j in range(len(attestation.custody_bits_blocks[i])):
                if attestation.aggregation_bits[j]:
                    attestation.custody_bits_blocks[i][j] = \
                        spec.compute_custody_bit(custody_secrets[j], test_vector) ^ (not valid_custody_bits)

    if signed:
        sign_attestation(spec, state, attestation)

    return attestation


def get_valid_on_time_attestation(spec, state, slot=None, index=None,
                                  shard_transition=None, valid_custody_bits=None, signed=False):
    '''
    Construct on-time attestation for next slot
    '''
    if slot is None:
        slot = state.slot
    if index is None:
        index = 0

    return get_valid_attestation(
        spec,
        state,
        slot=slot,
        index=index,
        shard_transition=shard_transition,
        valid_custody_bits=valid_custody_bits,
        signed=signed,
        on_time=True,
    )


def get_valid_late_attestation(spec, state, slot=None, index=None, signed=False, shard_transition=None):
    '''
    Construct on-time attestation for next slot
    '''
    if slot is None:
        slot = state.slot
    if index is None:
        index = 0

    return get_valid_attestation(spec, state, slot=slot, index=index,
                                 signed=signed, on_time=False, shard_transition=shard_transition)


def get_valid_attestation(spec,
                          state,
                          slot=None,
                          index=None,
                          filter_participant_set=None,
                          shard_transition=None,
                          valid_custody_bits=None,
                          signed=False,
                          on_time=True):
    # If filter_participant_set filters everything, the attestation has 0 participants, and cannot be signed.
    # Thus strictly speaking invalid when no participant is added later.
    if slot is None:
        slot = state.slot
    if index is None:
        index = 0

    attestation_data = build_attestation_data(
        spec, state, slot=slot, index=index, shard_transition=shard_transition, on_time=on_time
    )

    beacon_committee = spec.get_beacon_committee(
        state,
        attestation_data.slot,
        attestation_data.index,
    )

    committee_size = len(beacon_committee)
    aggregation_bits = Bitlist[spec.MAX_VALIDATORS_PER_COMMITTEE](*([0] * committee_size))
    attestation = spec.Attestation(
        aggregation_bits=aggregation_bits,
        data=attestation_data,
    )
    # fill the attestation with (optionally filtered) participants, and optionally sign it
    fill_aggregate_attestation(spec, state, attestation, signed=signed, filter_participant_set=filter_participant_set)

    if spec.fork == PHASE1 and on_time:
        attestation = convert_to_valid_on_time_attestation(
            spec, state, attestation,
            shard_transition=shard_transition,
            valid_custody_bits=valid_custody_bits,
            signed=signed,
        )

    return attestation


def sign_aggregate_attestation(spec, state, attestation_data, participants: List[int]):
    signatures = []
    for validator_index in participants:
        privkey = privkeys[validator_index]
        signatures.append(
            get_attestation_signature(
                spec,
                state,
                attestation_data,
                privkey
            )
        )
    return bls.Aggregate(signatures)


def sign_indexed_attestation(spec, state, indexed_attestation):
    if spec.fork == PHASE0:
        participants = indexed_attestation.attesting_indices
        data = indexed_attestation.data
        indexed_attestation.signature = sign_aggregate_attestation(spec, state, data, participants)
    else:
        participants = spec.get_indices_from_committee(
            indexed_attestation.committee,
            indexed_attestation.attestation.aggregation_bits,
        )
        data = indexed_attestation.attestation.data
        if any(indexed_attestation.attestation.custody_bits_blocks):
            sign_on_time_attestation(spec, state, indexed_attestation.attestation)
        else:
            indexed_attestation.attestation.signature = sign_aggregate_attestation(spec, state, data, participants)


def sign_on_time_attestation(spec, state, attestation):
    if not any(attestation.custody_bits_blocks):
        sign_attestation(spec, state, attestation)
        return

    committee = spec.get_beacon_committee(state, attestation.data.slot, attestation.data.index)
    signatures = []
    for block_index, custody_bits in enumerate(attestation.custody_bits_blocks):
        for participant, abit, cbit in zip(committee, attestation.aggregation_bits, custody_bits):
            if not abit:
                continue
            signatures.append(get_attestation_custody_signature(
                spec,
                state,
                attestation.data,
                block_index,
                cbit,
                privkeys[participant]
            ))

    attestation.signature = bls.Aggregate(signatures)


def get_attestation_custody_signature(spec, state, attestation_data, block_index, bit, privkey):
    domain = spec.get_domain(state, spec.DOMAIN_BEACON_ATTESTER, attestation_data.target.epoch)
    signing_root = spec.compute_signing_root(
        spec.AttestationCustodyBitWrapper(
            attestation_data_root=attestation_data.hash_tree_root(),
            block_index=block_index,
            bit=bit,
        ),
        domain,
    )
    return bls.Sign(privkey, signing_root)


def sign_attestation(spec, state, attestation):
    if spec.fork == PHASE1 and any(attestation.custody_bits_blocks):
        sign_on_time_attestation(spec, state, attestation)
        return

    participants = spec.get_attesting_indices(
        state,
        attestation.data,
        attestation.aggregation_bits,
    )

    attestation.signature = sign_aggregate_attestation(spec, state, attestation.data, participants)


def get_attestation_signature(spec, state, attestation_data, privkey):
    domain = spec.get_domain(state, spec.DOMAIN_BEACON_ATTESTER, attestation_data.target.epoch)
    signing_root = spec.compute_signing_root(attestation_data, domain)
    return bls.Sign(privkey, signing_root)


def fill_aggregate_attestation(spec, state, attestation, signed=False, filter_participant_set=None):
    """
     `signed`: Signing is optional.
     `filter_participant_set`: Optional, filters the full committee indices set (default) to a subset that participates
    """
    beacon_committee = spec.get_beacon_committee(
        state,
        attestation.data.slot,
        attestation.data.index,
    )
    # By default, have everyone participate
    participants = set(beacon_committee)
    # But optionally filter the participants to a smaller amount
    if filter_participant_set is not None:
        participants = filter_participant_set(participants)
    for i in range(len(beacon_committee)):
        attestation.aggregation_bits[i] = beacon_committee[i] in participants

    if signed and len(participants) > 0:
        sign_attestation(spec, state, attestation)


def add_attestations_to_state(spec, state, attestations, slot):
    if state.slot < slot:
        spec.process_slots(state, slot)
    for attestation in attestations:
        spec.process_attestation(state, attestation)


def next_epoch_with_attestations(spec,
                                 state,
                                 fill_cur_epoch,
                                 fill_prev_epoch):
    assert state.slot % spec.SLOTS_PER_EPOCH == 0

    post_state = state.copy()
    signed_blocks = []
    for _ in range(spec.SLOTS_PER_EPOCH):
        block = build_empty_block_for_next_slot(spec, post_state)
        if fill_cur_epoch and post_state.slot >= spec.MIN_ATTESTATION_INCLUSION_DELAY:
            slot_to_attest = post_state.slot - spec.MIN_ATTESTATION_INCLUSION_DELAY + 1
            committees_per_slot = spec.get_committee_count_at_slot(state, slot_to_attest)
            if slot_to_attest >= spec.compute_start_slot_at_epoch(spec.get_current_epoch(post_state)):
                for index in range(committees_per_slot):
                    cur_attestation = get_valid_attestation(spec, post_state, slot_to_attest, index=index, signed=True)
                    block.body.attestations.append(cur_attestation)

        if fill_prev_epoch:
            slot_to_attest = post_state.slot - spec.SLOTS_PER_EPOCH + 1
            committees_per_slot = spec.get_committee_count_at_slot(state, slot_to_attest)
            for index in range(committees_per_slot):
                prev_attestation = get_valid_attestation(
                    spec, post_state, slot_to_attest, index=index, signed=True, on_time=False)
                block.body.attestations.append(prev_attestation)

        if spec.fork == PHASE1:
            fill_block_shard_transitions_by_attestations(spec, post_state, block)

        signed_block = state_transition_and_sign_block(spec, post_state, block)
        signed_blocks.append(signed_block)

    return state, signed_blocks, post_state


def prepare_state_with_attestations(spec, state, participation_fn=None):
    """
    Prepare state with attestations according to the ``participation_fn``.
    If no ``participation_fn``, default to "full" -- max committee participation at each slot.

    participation_fn: (slot, committee_index, committee_indices_set) -> participants_indices_set
    """
    # Go to start of next epoch to ensure can have full participation
    next_epoch(spec, state)

    start_slot = state.slot
    start_epoch = spec.get_current_epoch(state)
    next_epoch_start_slot = spec.compute_start_slot_at_epoch(start_epoch + 1)
    attestations = []
    for _ in range(spec.SLOTS_PER_EPOCH + spec.MIN_ATTESTATION_INCLUSION_DELAY):
        # create an attestation for each index in each slot in epoch
        if state.slot < next_epoch_start_slot:
            for committee_index in range(spec.get_committee_count_at_slot(state, state.slot)):
                def temp_participants_filter(comm):
                    if participation_fn is None:
                        return comm
                    else:
                        return participation_fn(state.slot, committee_index, comm)
                attestation = get_valid_attestation(spec, state, index=committee_index,
                                                    filter_participant_set=temp_participants_filter, signed=True)
                if any(attestation.aggregation_bits):  # Only if there is at least 1 participant.
                    attestations.append(attestation)
        # fill each created slot in state after inclusion delay
        if state.slot >= start_slot + spec.MIN_ATTESTATION_INCLUSION_DELAY:
            inclusion_slot = state.slot - spec.MIN_ATTESTATION_INCLUSION_DELAY
            include_attestations = [att for att in attestations if att.data.slot == inclusion_slot]
            add_attestations_to_state(spec, state, include_attestations, state.slot)
        next_slot(spec, state)

    assert state.slot == next_epoch_start_slot + spec.MIN_ATTESTATION_INCLUSION_DELAY
    assert len(state.previous_epoch_attestations) == len(attestations)

    return attestations


_prep_state_cache_dict = LRU(size=10)


def cached_prepare_state_with_attestations(spec, state):
    """
    Cached version of prepare_state_with_attestations,
    but does not return anything, and does not support a participation fn argument
    """
    # If the pre-state is not already known in the LRU, then take it,
    # prepare it with attestations, and put it in the LRU.
    # The input state is likely already cached, so the hash-tree-root does not affect speed.
    key = (spec.fork, state.hash_tree_root())
    global _prep_state_cache_dict
    if key not in _prep_state_cache_dict:
        prepare_state_with_attestations(spec, state)
        _prep_state_cache_dict[key] = state.get_backing()  # cache the tree structure, not the view wrapping it.

    # Put the LRU cache result into the state view, as if we transitioned the original view
    state.set_backing(_prep_state_cache_dict[key])


def fill_block_shard_transitions_by_attestations(spec, state, block):
    block.body.shard_transitions = [spec.ShardTransition()] * spec.MAX_SHARDS
    for attestation in block.body.attestations:
        shard = spec.get_shard(state, attestation)
        if attestation.data.slot == state.slot:
            temp_state = state.copy()
            transition_to(spec, temp_state, slot=block.slot)
            shard_transition = spec.get_shard_transition(temp_state, shard, [])
            block.body.shard_transitions[shard] = shard_transition
