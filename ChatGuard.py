import asyncio
import configparser
import logging
import re
from contextlib import suppress
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session import aiohttp
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.enums.parse_mode import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

config = configparser.ConfigParser()
config.read('config.ini')

TOKEN = config['telegram']['TOKEN']
CHAT_LINK = config['telegram']['CHAT_LINK']

logging.basicConfig(level=logging.INFO)

scheduler = AsyncIOScheduler()
scheduler.start()

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# Routers
private_router = Router()
private_router.message.filter(F.chat.type == "private")

group_router = Router()
group_router.message.filter(F.chat.type != "private")


# Helper Functions
async def delete_webhook_with_retry(bot1: Bot, retries: int = 3, delay: int = 5):
    for attempt in range(retries):
        try:
            await bot1.delete_webhook(drop_pending_updates=True)
            print("Webhook deleted successfully.")
            return
        except aiohttp.ClientConnectorError as e:
            print(f"Network error on attempt {attempt + 1}/{retries}: {e}")
        except Exception as e:
            print(f"Unexpected error on attempt {attempt + 1}/{retries}: {e}")
        await asyncio.sleep(delay)
    print("Failed to delete webhook after several attempts.")


async def is_bot_admin(chat_id: int):
    bot_status = await bot.get_chat_member(chat_id, bot.id)
    return bot_status.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]


async def is_user_admin(chat_id: int, user_id: int):
    user_status = await bot.get_chat_member(chat_id, user_id)
    return user_status.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]


async def check_admin(message: types.Message):
    if not await is_bot_admin(message.chat.id):
        await message.reply("<b>❌ Бот не является администратором чата!</b>")
        return False

    if not await is_user_admin(message.chat.id, message.from_user.id):
        await message.reply("<b>❌ Вы не администратор!</b>")
        return False

    return True


async def send_error(message: types.Message, error_text: str):
    try:
        await message.reply(f"<b>❌ {error_text}</b>", parse_mode='HTML')
    except Exception as e:
        logging.error(f"Failed to send error message: {e}")


def parse_time(time_str: str):
    # Example implementation, customize as needed
    match = re.match(r'(\d+)([smhd])', time_str)
    if not match:
        return None, None

    amount, unit = match.groups()
    amount = int(amount)

    now = datetime.utcnow()
    match unit:
        case 's':
            until_date = now + timedelta(seconds=amount)
            duration_str = f"{amount} sec."
        case 'm':
            until_date = now + timedelta(minutes=amount)
            duration_str = f"{amount} min."
        case 'h':
            until_date = now + timedelta(hours=amount)
            duration_str = f"{amount} h."
        case 'd':
            until_date = now + timedelta(days=amount)
            duration_str = f"{amount} d."
        case 'w':
            until_date = now + timedelta(weeks=amount)
            duration_str = f"{amount} w."
        case 'M':
            until_date = now + timedelta(days=30 * amount)  # Approximate a month as 30 days
            duration_str = f"{amount} M."
        case 'y':
            until_date = now + timedelta(days=365 * amount)  # Approximate a year as 365 days
            duration_str = f"{amount} y."
        case _:
            return None, None

    return until_date, duration_str


async def send_invite(user_id: int):
    try:
        await bot.send_message(user_id, CHAT_LINK)
        logging.info(f"Invite sent to user {user_id}")
    except Exception as e:
        logging.error(f"Failed to send invite: {e}")


# Commands
@private_router.message(Command("start"))
async def start(message: types.Message):
    await message.reply("Этот бот создан для поддержания дружественной атмосферы в чате ☺️")


@group_router.message(Command("help"))
async def help_message(message: types.Message):
    help_text = """
    <b>Available Commands:</b>
<b>/start</b> - Starts the bot and sends a welcome message.
<b>/help</b> - Sends a list of available commands and their descriptions.
<b>/info</b> - Sends information about the bot.

<b>Admin Commands:</b>
<b>/mute &lt;time&gt;</b> - Mutes a user for the specified time. Time can be in hours (h), days (d), or weeks (w).
<b>/unmute</b> - Removes all restrictions from the user, allowing them to speak again.
<b>/ban &lt;time&gt;</b> - Bans a user for the specified time. Time can be in hours (h), days (d), or weeks (w).
<b>/unban</b> - Removes the ban from the user.
    """
    await message.reply(help_text, parse_mode='HTML')


@group_router.message(Command("info"))
async def info(message: types.Message):
    user_id = message.from_user.id
    try:
        await bot.send_message(user_id, 'This bot is created by @morry_dev.')
        await message.reply('Information sent to your private messages.')
    except Exception as e:
        logging.error(f"Failed to send message: {e}")
        await message.reply("Failed to send information to your private messages.")


@private_router.message()
async def private(message: types.Message):
    await message.reply("😔 <b>Бот работает только в группах</b>")


@group_router.message(Command("ban"))
async def func_kick(message: types.Message):
    logging.info("Ban command received")
    if not await check_admin(message):
        logging.info("User is not admin")
        return

    reply_message = message.reply_to_message
    if not reply_message:
        await send_error(message, "Вам нужно сделать это в ответ на сообщение пользователя!")
        return

    user_to_kick_id = reply_message.from_user.id
    moderator_id = message.from_user.id

    if await is_user_admin(message.chat.id, user_to_kick_id):
        await send_error(message, "Нельзя удалить администратора!")
        return

    try:
        await bot.ban_chat_member(chat_id=message.chat.id, user_id=user_to_kick_id)
        logging.info(f"User {reply_message.from_user.id} banned")
        await message.answer(
            f"🚫 <a href='tg://user?id={user_to_kick_id}'>{reply_message.from_user.full_name}</a> заблокирован навсегда\n"
            f"👤 Модератор: <a href='tg://user?id={moderator_id}'>{message.from_user.first_name}</a>", parse_mode='HTML')
        logging.info("Ban message sent successfully")
    except TelegramBadRequest as e:
        await send_error(message, f"Не удалось удалить пользователя: {e}")
        logging.error(f"Failed to kick user: {e}")
    except Exception as e:
        # Ловим любые другие возможные исключения
        await send_error(message, f"Произошла ошибка: {e}")
        logging.error(f"Unexpected error: {e}")


@group_router.message(Command("unban"))
async def func_unban(message: types.Message):
    if not await check_admin(message):
        return

    reply_message = message.reply_to_message
    if not reply_message:
        await send_error(message, "Вам нужно сделать это в ответ на сообщение пользователя!")
        return
    try:
        await bot.unban_chat_member(chat_id=message.chat.id, user_id=reply_message.from_user.id, only_if_banned=True)
        await message.answer("✅ Блокировка была снята")

        chat_link = CHAT_LINK  # Make sure CHAT_LINK is properly defined
        await bot.send_message(reply_message.from_user.id, chat_link)

    except Exception as e:
        # Log or handle the exception
        await send_error(message, f"Произошла ошибка: {str(e)}")


@group_router.message(Command("mute"))
async def func_mute(message: types.Message, ):
    logging.info("Mute command received")
    if not await check_admin(message):
        logging.info("User is not admin")
        return

    command_text = message.text.split(maxsplit=1)
    logging.info(f"Command text: {command_text}")

    if len(command_text) < 2:
        await send_error(message, "Вам нужно указать аргументы команды!")
        return

    args = command_text[1].strip()
    logging.info(f"Arguments: '{args}'")

    if not args:
        await send_error(message, "Не указаны аргументы для команды!")
        return

    # Process args here
    reply_message = message.reply_to_message
    if not reply_message:
        await send_error(message, "Вам нужно ответить на сообщение пользователя, которого вы хотите заглушить!")
        return

    user_to_mute_id = reply_message.from_user.id
    if await is_user_admin(message.chat.id, user_to_mute_id):
        await send_error(message, "Нельзя заглушить администратора!")
        return

    args = command_text.args.strip()
    if ' ' in args:
        time_str, reason = args.split(' ', 1)
    else:
        time_str = args
        reason = None

    until_date, duration_str = parse_time(time_str)

    # Debugging: Print or log parsed values
    print(f"Parsed time string: {time_str}")
    print(f"Parsed until_date: {until_date}")
    print(f"Parsed duration_str: {duration_str}")
    print(f"Parsed reason: {reason}")

    if until_date is None:
        await send_error(message, "Не удалось разобрать время. Пожалуйста, используйте правильный формат времени.")
        return

    with suppress(TelegramBadRequest):
        await bot.restrict_chat_member(
            chat_id=message.chat.id,
            user_id=user_to_mute_id,
            until_date=until_date,
            permissions=types.ChatPermissions(can_send_messages=False)
        )

        mute_message = (
            f"🔇 <a href='tg://user?id={user_to_mute_id}'>{reply_message.from_user.full_name}</a> был заглушен"
        )
        if duration_str:
            mute_message += f" на {duration_str}"
        if reason:
            mute_message += f"\nПричина: {reason}"
        else:
            mute_message += "!"

        await message.answer(mute_message, parse_mode='HTML')


@group_router.message(Command("unmute"))
async def func_unmute(message: types.Message):
    if not await check_admin(message):
        return

    reply_message = message.reply_to_message
    if not reply_message:
        await send_error(message, "Вам нужно сделать это в ответ на сообщение пользователя!")
        return

    mention = reply_message.from_user.mention_html(reply_message.from_user.first_name)
    await bot.restrict_chat_member(
        chat_id=message.chat.id,
        user_id=reply_message.from_user.id,
        permissions=types.ChatPermissions(can_send_messages=True, can_send_other_messages=True)
    )
    await message.answer(f"🎉 Все ограничения с пользователя <b>{mention}</b> были сняты!")


async def main():
    dp.include_router(private_router)
    dp.include_router(group_router)

    await delete_webhook_with_retry(bot)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
    scheduler.start()
