# Owner @UR_Father
from pyrogram import filters
from pyrogram.types import Message

from AbhiXMusic import app
from AbhiXMusic.core.call import Abhi

welcome = 20
close = 30


@app.on_message(filters.video_chat_started, group=welcome)
@app.on_message(filters.video_chat_ended, group=close)
async def welcome(_, message: Message):
    await Abhi.stop_stream_force(message.chat.id)
