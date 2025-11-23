import pytest

from bot.services import visual_captcha_logic as captcha_logic


@pytest.mark.asyncio
async def test_save_and_get_captcha_data(fake_redis):
    user_id = 123456
    await captcha_logic.save_captcha_data(user_id, "ANSWER", "test_group", attempts=2)

    data = await captcha_logic.get_captcha_data(user_id)

    assert data is not None
    assert data["captcha_answer"] == "ANSWER"
    assert data["group_name"] == "test_group"
    assert data["attempts"] == 2


@pytest.mark.asyncio
async def test_get_captcha_keyboard_fallback_for_invalid_link():
    keyboard = await captcha_logic.get_captcha_keyboard("invalid_link")

    assert keyboard.inline_keyboard[0][0].callback_data == "captcha_fallback"
    assert keyboard.inline_keyboard[0][0].text == "🧩 Пройти капчу"

