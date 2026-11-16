"""Resolve a shot's independent actor states, including scoped listener edits."""

def pose_for(lines, index, cast, cid, cast_for):
    carry = {}
    variant = 0
    result = ('calm', 0, None)
    for i, line in enumerate(lines[:index + 1]):
        speaker = cid in (line.get('speakers') or [line.get('speaker')])
        if cid not in cast_for(lines, i, cast):
            carry = {}
            if speaker:
                variant += 1
            continue
        if speaker:
            carry = dict(emotion=line.get('emotion') or 'calm', body_mood=line.get('body_mood'))
            variant += 1
        current = dict(carry)
        current.update(line.get('actor_states', {}).get(cid) or {})
        if i < index:
            for segment in line.get('performance_segments') or []:
                if speaker:
                    current.update(emotion=segment.get('emotion') or current.get('emotion', 'calm'), body_mood=segment.get('body_mood'))
                current.update(segment.get('actor_states', {}).get(cid) or {})
        mood = current.get('emotion') or 'calm'
        body = current.get('body_mood')
        result = (mood, max(0, variant - 1), body or None)
        if speaker or line.get('listener_state_persist', True):
            carry = current
    return result
