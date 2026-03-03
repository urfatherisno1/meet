# welcome_handler.py
# Final production version with adjusted positions
# Owner @UR_Father

from AbhiXMusic import app
from pyrogram.errors import RPCError
from pyrogram.types import ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton
from typing import Union, Optional
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageChops, ImageOps
import random
import asyncio
import os
import time
from logging import getLogger
from pyrogram import Client, filters, enums
from pyrogram.enums import ParseMode, ChatMemberStatus
from AbhiXMusic.utils.database import add_served_chat, get_assistant, is_active_chat
from AbhiXMusic.misc import SUDOERS
from AbhiXMusic.mongo.afkdb import PROCESS
from AbhiXMusic.utils.Abhi_ban import admin_filter

LOGGER = getLogger(__name__)

random_photo = [
    "https://telegra.ph/file/1949480f01355b4e87d26.jpg",
    "https://telegra.ph/file/3ef2cc0ad2bc548bafb30.jpg",
    "https://telegra.ph/file/a7d663cd2de689b811729.jpg",
    "https://telegra.ph/file/6f19dc23847f5b005e922.jpg",
    "https://telegra.ph/file/2973150dd62fd27a3a6ba.jpg",
]

# --------------------------------------------------------------------------------- #
class WelDatabase:
    def __init__(self):
        self.data = {}

    async def find_one(self, chat_id):
        return chat_id in self.data

    async def add_wlcm(self, chat_id):
        if chat_id not in self.data:
            self.data[chat_id] = {"state": "on"}

    async def rm_wlcm(self, chat_id):
        if chat_id in self.data:
            del self.data[chat_id]

wlcm = WelDatabase()

class temp:
    ME = None
    CURRENT = 2
    CANCEL = False
    MELCOW = {}
    U_NAME = None
    B_NAME = None

# --------------------- Helper: create circular profile ----------------------- #
def make_circular(im: Image.Image, diameter: int) -> Image.Image:
    """
    Resize image to circular shape with transparent background
    """
    im = im.convert("RGBA")
    im = ImageOps.fit(im, (diameter, diameter), centering=(0.5, 0.5))
    
    # Create circular mask
    mask = Image.new("L", (diameter, diameter), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, diameter, diameter), fill=255)
    
    # Apply mask
    output = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    output.paste(im, (0, 0))
    output.putalpha(mask)
    
    return output

# --------------------- Main: compose welcome image ----------------------- #
def welcomepic(
    pic_path: str,
    first_name: str,
    group_name: str,
    user_id: int,
    username: Optional[str],
    member_count: int,
    background_path: str = "AbhiXMusic/assets/wel2.png",
    font_path: str = "AbhiXMusic/assets/Abhi.ttf",
):
    """
    Creates welcome image with properly positioned text values
    Template already has labels, we only draw VALUES
    """
    os.makedirs("downloads", exist_ok=True)

    # Open background
    try:
        bg = Image.open(background_path).convert("RGBA")
    except Exception as e:
        LOGGER.error("Could not open background (%s): %s", background_path, e)
        raise

    W, H = bg.size
    
    # ==================== PROFILE CIRCLE ====================
    circle_diameter = int(H * 0.43)  # Size to fit perfectly in cyan ring
    circle_x = int(W * 0.12)         # Left position
    circle_y = int(H * 0.15)         # Top position

    # Load profile picture
    try:
        pfp = Image.open(pic_path).convert("RGBA")
    except Exception:
        try:
            pfp = Image.open("AbhiXMusic/assets/upic.png").convert("RGBA")
        except Exception:
            LOGGER.warning("No profile picture available, using placeholder.")
            pfp = Image.new("RGBA", (circle_diameter, circle_diameter), (200, 200, 200, 255))

    # Make circular and paste
    circular = make_circular(pfp, circle_diameter)
    bg.paste(circular, (circle_x, circle_y), circular)

    draw = ImageDraw.Draw(bg)

    # ==================== FONTS ====================
    try:
        font_right = ImageFont.truetype(font_path, size=int(H * 0.038))   # Right side
        font_bottom = ImageFont.truetype(font_path, size=int(H * 0.042))  # Bottom box
    except Exception:
        LOGGER.warning("Font not found, using default")
        font_right = ImageFont.load_default()
        font_bottom = ImageFont.load_default()

    text_color = (200, 245, 255)  # Bright cyan-white

    # ==================== RIGHT SIDE VALUES ====================
    # Value after "Group :" label
    group_label_x = int(W * 0.600)
    group_label_y = int(H * 0.413)
    draw.text((group_label_x, group_label_y), group_name, font=font_right, fill=text_color)
    
    # Value after "Members :" label
    members_x = int(W * 0.630)
    members_y = int(H * 0.496)
    draw.text((members_x, members_y), str(member_count), font=font_right, fill=text_color)

    # ==================== BOTTOM BOX VALUES ====================
    # X position for all bottom values (after the label colons)
    value_x = int(W * 0.35)
    
    # Y positions for each line
    name_y = int(H * 0.720)
    username_y = int(H * 0.775)
    id_y = int(H * 0.835)
    members_y = int(H * 0.889)
    
    # Prepare values
    name_text = first_name[:25] if len(first_name) > 25 else first_name
    username_text = f"@{username}" if username else "None"
    id_text = str(user_id)
    members_text = str(member_count)
    
    # Draw function with shadow for better visibility
    def draw_value(x, y, text, font):
        draw.text((x+1, y+1), text, font=font, fill=(0, 0, 0, 120))  # Shadow
        draw.text((x, y), text, font=font, fill=text_color)          # Main text
    
    # Draw all bottom values
    draw_value(value_x, name_y, name_text, font_bottom)
    draw_value(value_x, username_y, username_text, font_bottom)
    draw_value(value_x, id_y, id_text, font_bottom)
    draw_value(value_x, members_y, members_text, font_bottom)

    # Save output
    out_path = f"downloads/welcome#{user_id}.png"
    bg.save(out_path)
    return out_path

# ------------------ Command to toggle welcome --------------------- #
@app.on_message(filters.command("welcome") & ~filters.private)
async def auto_state(_, message):
    usage = "**ᴜsᴀɢᴇ:**\n**⦿ /welcome [on|off]**"
    if len(message.command) == 1:
        return await message.reply_text(usage)

    chat_id = message.chat.id
    user = await app.get_chat_member(chat_id, message.from_user.id)
    if user.status in (enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER):
        A = await wlcm.find_one(chat_id)
        state = message.text.split(None, 1)[1].strip().lower()
        if state == "off":
            if A:
                await message.reply_text("**ᴡᴇʟᴄᴏᴍᴇ ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴ ᴀʟʀᴇᴀᴅʏ ᴅɪsᴀʙʟᴇᴅ !**")
            else:
                await wlcm.add_wlcm(chat_id)
                await message.reply_text(f"**ᴅɪsᴀʙʟᴇᴅ ᴡᴇʟᴄᴏᴍᴇ ɪɴ** {message.chat.title}")
        elif state == "on":
            if not A:
                await message.reply_text("**ᴇɴᴀʙʟᴇᴅ ᴡᴇʟᴄᴏᴍᴇ ɴᴏᴛɪғɪᴄᴀᴛɪᴏɴ.**")
            else:
                await wlcm.rm_wlcm(chat_id)
                await message.reply_text(f"**ᴇɴᴀʙʟᴇᴅ ᴡᴇʟᴄᴏᴍᴇ ɪɴ** {message.chat.title}")
        else:
            await message.reply_text(usage)
    else:
        await message.reply("**sᴏʀʀʏ ᴏɴʟʏ ᴀᴅᴍɪɴs ᴄᴀɴ ᴇɴᴀʙʟᴇ ᴡᴇʟᴄᴏᴍᴇ!**")

# ------------------ Chat member update handler --------------------- #
@app.on_chat_member_updated(filters.group, group=-3)
async def greet_new_member(_, member: ChatMemberUpdated):
    chat_id = member.chat.id
    count = await app.get_chat_members_count(chat_id)
    A = await wlcm.find_one(chat_id)
    if A:
        return

    if member.new_chat_member and not member.old_chat_member and member.new_chat_member.status != "kicked":
        user = member.new_chat_member.user
        
        # Download profile picture
        try:
            pic = await app.download_media(user.photo.big_file_id, file_name=f"pp{user.id}.png")
        except Exception:
            pic = "AbhiXMusic/assets/upic.png"

        # Delete previous welcome message
        if temp.MELCOW.get(f"welcome-{chat_id}") is not None:
            try:
                await temp.MELCOW[f"welcome-{chat_id}"].delete()
            except Exception as e:
                LOGGER.error(e)

        try:
            # Create welcome image
            welcomeimg = welcomepic(
                pic_path=pic,
                first_name=user.first_name or (user.username or "User"),
                group_name=member.chat.title or "Group",
                user_id=user.id,
                username=user.username,
                member_count=count,
            )

            button_text = "๏ ᴠɪᴇᴡ ɴᴇᴡ ᴍᴇᴍʙᴇʀ ๏"
            add_button_text = "✙ ᴋɪᴅɴᴀᴘ ᴍᴇ ✙"
            deep_link = f"tg://openmessage?user_id={user.id}"
            add_link = f"https://t.me/{app.username}?startgroup=true"

            msg = await app.send_photo(
                chat_id,
                photo=welcomeimg,
                caption=f"""
**⎊─────☵ ᴡᴇʟᴄᴏᴍᴇ ☵─────⎊**

**▬▭▬▭▬▭▬▭▬▭▬▭▬▭▬**

**☉ ɴᴀᴍᴇ ⧽** {user.mention}
**☉ ɪᴅ ⧽** `{user.id}`
**☉ ᴜ_ɴᴀᴍᴇ ⧽** @{user.username if user.username else 'None'}
**☉ ᴛᴏᴛᴀʟ ᴍᴇᴍʙᴇʀs ⧽** {count}

**▬▭▬▭▬▭▬▭▬▭▬▭▬▭▬**

**⎉──────▢✭ 侖 ✭▢──────⎉**
""",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(button_text, url=deep_link)],
                    [InlineKeyboardButton(text=add_button_text, url=add_link)],
                ])
            )

            temp.MELCOW[f"welcome-{chat_id}"] = msg

            # Auto-delete after 3 minutes
            await asyncio.sleep(180)
            try:
                await msg.delete()
            except Exception:
                pass

        except Exception as e:
            LOGGER.error("Error creating/sending welcome image: %s", e)
            try:
                await app.send_message(
                    chat_id,
                    f"Welcome {user.mention}!\nID: `{user.id}`\nUsername: @{user.username if user.username else 'None'}",
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as ex:
                LOGGER.error("Fallback message also failed: %s", ex)
