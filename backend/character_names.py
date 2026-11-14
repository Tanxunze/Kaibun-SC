"""One identity map from characters.toml for script prompts and speech-only readings."""
import re


def identity(character):
    kana = getattr(character, 'name_kana', None) or ''
    pieces = kana.split()
    short = getattr(character, 'short_name', None) or character.name
    return dict(id=character.id, name=character.name, name_ja=character.name,
                name_kana=kana, name_zh=getattr(character, 'name_zh', None) or character.name,
                short_name=short, short_kana=pieces[-1] if len(pieces) == 2 else '')


def name_reference(characters):
    return [identity(c) for c in characters.values() if getattr(c, 'name_kana', None)]


NAME_RULES = (
    '人物姓名以character_names中同一id的name_ja（日文原名）、name_kana（读法）、name_zh（中文名）为准。'
    'ja使用日文原名或符合角色关系的原作称呼，zh使用对应中文名或简称，不把中文译名音译回日文。'
    '不要在台词里附读音说明。浅倉透＝あさくら とおる＝浅仓透；透、透ちゃん、透先輩的透均读とおる，'
    '不是とう、とうる、とおり、すけ。保留各人原有称呼习惯，不强行每次称全名。'
)


def speech_names(text, characters):
    """Render recognized names in kana only for TTS. Displayed script stays intact.

    Longest matches run once so a replacement is never transformed again. The
    ambiguous single kanji 透 is restricted to name suffixes and utterance/particle
    contexts; ordinary 透明、透ける、浸透、見透かす are untouched.
    """
    replacements = {}
    for c in characters.values():
        if not getattr(c, 'name_kana', None):
            continue
        row = identity(c)
        if not row['name_kana']:
            continue
        full = row['name_kana'].replace(' ', '').replace('　', '')
        for name in {row['name_ja'], row['name_zh']}:
            replacements[name] = full
        short, reading = row['short_name'], row['short_kana']
        if reading and short != '透' and re.search(r'[一-龯々]', short):
            replacements[short] = reading
        if short and reading and row['name_ja'].endswith(short):
            surname = row['name_ja'][:-len(short)]
            for space in (' ', '　'):
                if surname:
                    replacements[surname + space + short] = full
            # Never reinterpret common standalone surnames as ordinary words.
            for suffix in ('さん', 'ちゃん', '先輩', 'さま', '様', 'くん', '君'):
                if surname:
                    replacements[surname + suffix] = row['name_kana'].split()[0] + suffix
    if replacements:
        pattern = '|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True))
        text = re.sub(pattern, lambda m: replacements[m[0]], text)
    toru = characters.get('toru')
    if toru and getattr(toru, 'name_kana', None):
        # A quoted mention, honorific or following particle identifies the name.
        text = re.sub(r'(?<![一-龯々])透(?=(?:ちゃん|さん|先輩|さま|様|くん|君|は|が|を|に|と|の|も|って|なら|[、。，．！？!?…「」『』\s]|$))', 'とおる', text)
    return text
