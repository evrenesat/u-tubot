from utubot.captions.meaning import meaning_block, reference_text, token_f1


def test_token_f1_rewards_the_words_a_reference_has():
    assert token_f1("Hello there, friend!", "hello there friend") == 1.0
    assert token_f1("Hello there", "hello there friend") == 0.8


def test_token_f1_is_zero_without_shared_words():
    assert token_f1("completely different", "hello there") == 0.0
    assert token_f1("", "hello") == 0.0


def test_reference_text_reads_timed_cues_and_plain_text(tmp_path):
    vtt = tmp_path / "ref.vtt"
    vtt.write_text(
        "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nनमस्ते दोस्त\n\n"
        "00:00:03.000 --> 00:00:04.000\nयह ठीक है\n",
        encoding="utf-8",
    )
    assert reference_text(vtt.read_text(encoding="utf-8")) == "नमस्ते दोस्त यह ठीक है"
    block = meaning_block("नमस्ते दोस्त", vtt, 0.5)
    assert block["score"] == 0.571 and block["passed"] is True

    plain = tmp_path / "ref.txt"
    plain.write_text("hello there", encoding="utf-8")
    assert meaning_block("hello there", plain, 0.5)["passed"] is True
    assert meaning_block("something else", plain, 0.5)["passed"] is False
