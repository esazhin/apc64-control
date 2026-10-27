from _apc64_host.domain.oled import OledText, name_warning, oled_cut


def test_names_are_cut_to_14_characters_and_non_ascii_shows_as_a_question_mark():
    assert oled_cut("Drums and Percussion Kit") == "Drums and Perc"
    assert OledText("Café").row0 == "Caf?"
    assert OledText("abc   ", "x" * 20).rows == ("abc", "x" * 14)
    assert oled_cut("CC30 → mpc") == "CC30 > mpc"


def test_a_long_page_name_is_warned_about_with_what_the_oled_shows():
    assert name_warning("page", "Drums and Percussion Kit") == \
        'page name longer than 14 characters, OLED shows "Drums and Perc"'
    assert name_warning("layout", "Café") == 'layout name has characters the OLED cannot show, OLED shows "Caf?"'
    assert name_warning("page", "Keys") is None


def test_the_idle_rows_show_the_layout_then_page_and_bank():
    idle = OledText.idle("Jam", 1, "Drums", 1, "Mix")
    assert idle.rows == ("Jam", "P1 Drums | B1")
    assert OledText.idle("Jam", 3, None, 2, None).rows == ("Jam", "P3 | B2")
    assert OledText.idle("Jam", 1, "Drums", None, None).rows == ("Jam", "P1 Drums")


def test_fixed_texts():
    assert OledText.no_layout().rows == ("No layout", "")
    assert OledText.blank().rows == ("", "")
    assert OledText.transient("Keys", "Page 2").rows == ("Keys", "Page 2")
