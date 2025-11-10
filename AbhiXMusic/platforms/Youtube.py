# Youtube.py  (Full replacement — copy-paste into AbhiXMusic/platforms/Youtube.py)
import asyncio
import os
import re
import json
import random
import aiohttp
import yt_dlp
import glob
from typing import Union, Tuple
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch
from AbhiXMusic.utils.database import is_on_off
from AbhiXMusic.utils.formatters import time_to_seconds
from os import getenv
from time import time

# -------------------------
# CONFIG (env)
# -------------------------
API_URL = getenv("YOUR_API_URL", "http://43.205.209.72:8000")
API_KEY = getenv("YOUR_API_KEY", "abhi_super_secret_key_change_me")
VIDEO_API_URL = getenv("VIDEO_API_URL", API_URL)
LOG_CHANNEL_ID = getenv("LOGGER_ID")  # optional
# If you want cookie path relative to other repo, set API_BASE_PATH env or edit here:
API_BASE_PATH = getenv("API_BASE_PATH", os.getcwd())  # default current working dir

# -------------------------
# Globals
# -------------------------
_global_aio_session: aiohttp.ClientSession = None


def _get_session():
    global _global_aio_session
    if _global_aio_session is None or _global_aio_session.closed:
        _global_aio_session = aiohttp.ClientSession()
    return _global_aio_session


# -------------------------
# Cookies helper
# -------------------------
def cookie_txt_file():
    # prefer cookie inside API_BASE_PATH/cookies/youtube.txt else look local ./cookies/*.txt
    cookie_file = os.path.join(API_BASE_PATH, "cookies", "youtube.txt")
    if os.path.exists(cookie_file):
        return cookie_file
    # fallback: any .txt inside ./cookies
    local_dir = os.path.join(os.getcwd(), "cookies")
    if os.path.isdir(local_dir):
        files = [os.path.join(local_dir, f) for f in os.listdir(local_dir) if f.endswith(".txt")]
        if files:
            return random.choice(files)
    return None


# -------------------------
# FFmpeg conversion helper
# -------------------------
async def run_ffmpeg_conversion(download_url: str, file_path: str, timeout: int = 60) -> bool:
    """Convert HLS/m3u8 stream into mp3 using ffmpeg. Returns True on success."""
    # Ensure downloads dir
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    cmd = f'ffmpeg -y -hide_banner -loglevel error -i "{download_url}" -vn -acodec libmp3lame -ab 192k "{file_path}"'
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return False
        # check size
        if os.path.exists(file_path) and os.path.getsize(file_path) > 50000:
            return True
        return False
    except Exception as e:
        print(f"[FFMPEG] Exception: {e}")
        return False


# -------------------------
# yt-dlp fallback download
# -------------------------
async def yt_dlp_audio_fallback(link: str) -> Union[str, None]:
    """Use local yt-dlp to download audio to downloads/<id>.mp3"""
    cookie_file = cookie_txt_file()
    if not cookie_file:
        print("[YT-DLP] No cookies available for yt-dlp fallback.")
        # still try without cookie but warn
    ydl_optssx = {
        "format": "bestaudio/best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "geo_bypass": True,
        "nocheckcertificate": True,
        "quiet": True,
        "no_warnings": True,
    }
    if cookie_file:
        ydl_optssx["cookiefile"] = cookie_file

    def download_sync():
        with yt_dlp.YoutubeDL(ydl_optssx) as x:
            info = x.extract_info(link, False)
            x.download([link])
            # convert to mp3 if postprocessor set, but we didn't set postproc here to keep ext predictable
            # choose resulting file by id and ext
            _id = info.get("id")
            _ext = info.get("ext", "mp3")
            path = os.path.join("downloads", f"{_id}.{_ext}")
            # if postprocessor did conversion to mp3, ensure .mp3
            if not os.path.exists(path) and os.path.exists(os.path.join("downloads", f"{_id}.mp3")):
                return os.path.join("downloads", f"{_id}.mp3")
            return path

    loop = asyncio.get_running_loop()
    try:
        os.makedirs("downloads", exist_ok=True)
        path = await loop.run_in_executor(None, download_sync)
        if path and os.path.exists(path) and os.path.getsize(path) > 50000:
            print(f"[YT-DLP] Download fallback succeeded: {path}")
            return path
        print("[YT-DLP] Download fallback produced file but it's missing or too small.")
        return None
    except Exception as e:
        print(f"[YT-DLP] fallback exception: {e}")
        return None


# -------------------------
# API helpers (requests to own Flask API)
# -------------------------
async def fetch_api_json(url: str, params: dict = None, timeout: int = 20) -> Union[dict, None]:
    session = _get_session()
    try:
        async with session.get(url, params=params, timeout=timeout) as resp:
            text = await resp.text()
            try:
                data = await resp.json()
                return data
            except Exception:
                # sometimes API prints logs to stdout + json, try to extract json substring
                try:
                    first_brace = text.find("{")
                    last_brace = text.rfind("}")
                    if first_brace != -1 and last_brace != -1:
                        return json.loads(text[first_brace:last_brace + 1])
                except Exception:
                    pass
                print(f"[API] invalid json from {url}. status={resp.status}. raw={text[:200]}")
                return None
    except aiohttp.ClientError as e:
        print(f"[API] network error calling {url}: {e}")
        return None
    except asyncio.TimeoutError:
        print(f"[API] timeout calling {url}")
        return None


# -------------------------
# Core: download_song
# -------------------------
async def download_song(link: str) -> Union[str, None]:
    """
    Returns local file path (downloads/<id>.mp3) or None.
    Flow:
      1) Use API: /song/<id>?api=API_KEY
         - if status done and link present => try to download/convert
      2) Fallback: ffmpeg convert if HLS
      3) Fallback: yt-dlp local
    """
    video_id = None
    try:
        # extract video id robustly
        if "v=" in link:
            video_id = link.split("v=")[-1].split("&")[0]
        elif "youtu.be/" in link:
            video_id = link.split("youtu.be/")[-1].split("?")[0].split("&")[0]
        else:
            video_id = link
    except Exception:
        video_id = link

    download_folder = "downloads"
    os.makedirs(download_folder, exist_ok=True)
    file_path = os.path.join(download_folder, f"{video_id}.mp3")

    # 0 - local cache
    if os.path.exists(file_path) and os.path.getsize(file_path) > 50000:
        print(f"[CACHE] already present: {file_path}")
        return file_path

    # 1 - call API /song/<id>
    if API_URL and API_KEY:
        api_url = f"{API_URL.rstrip('/')}/song/{video_id}"
        params = {"api": API_KEY}
        data = await fetch_api_json(api_url, params=params)
        if data:
            # normalize status
            status = data.get("status")
            # status might be boolean True/False, or string "true"/"done" etc
            status_str = str(status).lower() if status is not None else ""
            if status_str in ("done", "true", "ok"):
                # prefer link fields in order
                download_url = data.get("link") or data.get("audio_url") or data.get("video_url") or data.get("url")
                if not download_url:
                    print(f"[FAIL] API returned done but no url for {video_id}")
                else:
                    # if HLS => convert via ffmpeg (fast) else download binary
                    if ".m3u8" in download_url or "manifest/hls" in download_url or download_url.endswith(".m3u8"):
                        print(f"[API] HLS detected for {video_id}. Trying ffmpeg conversion.")
                        ok = await run_ffmpeg_conversion(download_url, file_path, timeout=60)
                        if ok:
                            return file_path
                        else:
                            print("[API] ffmpeg conversion failed, falling back to yt-dlp.")
                    else:
                        # binary download
                        session = _get_session()
                        try:
                            async with session.get(download_url, timeout=60) as r:
                                if r.status == 200:
                                    with open(file_path, "wb") as f:
                                        async for chunk in r.content.iter_chunked(8192):
                                            f.write(chunk)
                                    if os.path.exists(file_path) and os.path.getsize(file_path) > 50000:
                                        print(f"[API] downloaded file saved: {file_path}")
                                        return file_path
                                    else:
                                        print("[API] downloaded file too small / invalid, will fallback.")
                                else:
                                    print(f"[API] download url responded status {r.status}, fallback.")
                        except Exception as e:
                            print(f"[API] download exception: {e}")
            else:
                # API returned something but not done
                print(f"[API] status not done: {data.get('status')}")
        else:
            print("[API] No/parsing error response from API call.")

    else:
        print("[WARN] API_URL or API_KEY not configured - skipping API.")

    # 2 - attempt ffmpeg from direct youtube HLS if we can get it via yt-dlp -g
    cookie_file = cookie_txt_file()
    if cookie_file:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--cookies", cookie_file,
                "-g",
                "-f",
                "bestaudio/best",
                f"https://www.youtube.com/watch?v={video_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            stdout_text = stdout.decode().strip()
            stderr_text = stderr.decode().strip()
            if stdout_text:
                url_candidate = stdout_text.splitlines()[0]
                if url_candidate and (".m3u8" in url_candidate or "manifest/hls" in url_candidate):
                    print("[YT-DLP-G] got HLS url -> trying ffmpeg conversion")
                    ok = await run_ffmpeg_conversion(url_candidate, file_path, timeout=60)
                    if ok:
                        return file_path
                else:
                    # attempt direct binary fetch of candidate
                    session = _get_session()
                    try:
                        async with session.get(url_candidate, timeout=60) as r:
                            if r.status == 200:
                                with open(file_path, "wb") as f:
                                    async for chunk in r.content.iter_chunked(8192):
                                        f.write(chunk)
                                if os.path.exists(file_path) and os.path.getsize(file_path) > 50000:
                                    return file_path
                    except Exception:
                        pass
            else:
                # no stdout - check stderr warnings
                pass
        except Exception as e:
            print(f"[YT-DLP-G] error while probing: {e}")

    # 3 - fallback to local yt-dlp full download
    print("[FALLBACK] Using local yt-dlp download fallback.")
    final_path = await yt_dlp_audio_fallback(f"https://www.youtube.com/watch?v={video_id}")
    if final_path:
        return final_path

    print("[ERROR] All methods failed to get audio for", video_id)
    return None


# -------------------------
# download_video (API first then fallback)
# -------------------------
async def download_video(link: str):
    # extract id
    if "v=" in link:
        video_id = link.split("v=")[-1].split("&")[0]
    elif "youtu.be/" in link:
        video_id = link.split("youtu.be/")[-1].split("?")[0]
    else:
        video_id = link

    download_folder = "downloads"
    os.makedirs(download_folder, exist_ok=True)

    for ext in ["mp4", "webm", "mkv"]:
        temp_path = os.path.join(download_folder, f"{video_id}.{ext}")
        if os.path.exists(temp_path):
            return temp_path

    # API call
    if VIDEO_API_URL and API_KEY:
        api_url = f"{VIDEO_API_URL.rstrip('/')}/video/{video_id}"
        params = {"api": API_KEY}
        data = await fetch_api_json(api_url, params=params)
        if data:
            status = str(data.get("status", "")).lower()
            if status in ("done", "true", "ok"):
                download_url = data.get("link") or data.get("url")
                if download_url:
                    file_path = os.path.join(download_folder, f"{video_id}.mp4")
                    session = _get_session()
                    try:
                        async with session.get(download_url, timeout=120) as r:
                            if r.status == 200:
                                with open(file_path, "wb") as f:
                                    async for chunk in r.content.iter_chunked(8192):
                                        f.write(chunk)
                                if os.path.exists(file_path) and os.path.getsize(file_path) > 200000:
                                    return file_path
                    except Exception as e:
                        print(f"[API VIDEO] download error: {e}")
    # fallback: use yt-dlp to get direct url (not full download) or download
    cookie_file = cookie_txt_file()
    if cookie_file:
        try:
            proc = await asyncio.create_subprocess_exec(
                "yt-dlp",
                "--cookies", cookie_file,
                "-g",
                "-f",
                "best[height<=?720][width<=?1280]",
                f"https://www.youtube.com/watch?v={video_id}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if stdout:
                url_line = stdout.decode().splitlines()[0]
                return url_line
            else:
                return None
        except Exception as e:
            print(f"[yt-dlp-video] error: {e}")
            return None
    return None


# -------------------------
# utility: check_file_size
# -------------------------
async def check_file_size(link):
    async def get_format_info(link):
        cookie_file = cookie_txt_file()
        if not cookie_file:
            print("No cookies found. Cannot check file size.")
            return None

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies", cookie_file,
            "-J",
            link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            print(f'Error calling yt-dlp -J:\n{stderr.decode()}')
            return None
        try:
            return json.loads(stdout.decode())
        except Exception:
            return None

    def parse_size(formats):
        total_size = 0
        for fmt in formats:
            if "filesize" in fmt and isinstance(fmt["filesize"], (int, float)):
                total_size += fmt["filesize"]
        return total_size

    info = await get_format_info(link)
    if info is None:
        return None
    formats = info.get("formats", [])
    if not formats:
        return None
    total_size = parse_size(formats)
    return total_size


# -------------------------
# shell_cmd (used for playlist etc)
# -------------------------
async def shell_cmd(cmd):
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, errorz = await proc.communicate()
    if errorz:
        err = errorz.decode("utf-8")
        if "unavailable videos are hidden" in err.lower():
            return out.decode("utf-8")
        else:
            return err
    return out.decode("utf-8")


# -------------------------
# YouTubeAPI Class (same interface as original)
# -------------------------
class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.listbase = "https://youtube.com/playlist?list="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        text = ""
        offset = None
        length = None
        for message in messages:
            if offset:
                break
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        offset, length = entity.offset, entity.length
                        break
            if offset is None and message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        if offset is None:
            return None
        if offset is not None and length is not None:
            return text[offset: offset + length]
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None) -> Tuple[str, str, int, str, str]:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            vidid = result["id"]
            if str(duration_min) == "None":
                duration_sec = 0
            else:
                duration_sec = int(time_to_seconds(duration_min))
        return title, duration_min, duration_sec, thumbnail, vidid

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
        return title

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            duration = result["duration"]
        return duration

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
        return thumbnail

    async def video(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        try:
            downloaded_file = await download_video(link)
            if downloaded_file:
                # if it's a local file path - return 1,path
                return 1, downloaded_file
        except Exception as e:
            print(f"Video API failed: {e}")

        cookie_file = cookie_txt_file()
        if not cookie_file:
            return 0, "No cookies found. Cannot download video."

        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "--cookies", cookie_file,
            "-g",
            "-f",
            "best[height<=?720][width<=?1280]",
            f"{link}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if stdout:
            return 1, stdout.decode().split("\n")[0]
        else:
            return 0, stderr.decode()

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]

        cookie_file = cookie_txt_file()
        if not cookie_file:
            return []

        playlist = await shell_cmd(
            f"yt-dlp -i --get-id --flat-playlist --cookies {cookie_file} --playlist-end {limit} --skip-download {link}"
        )
        try:
            result = playlist.split("\n")
            for key in result:
                if key == "":
                    result.remove(key)
        except:
            result = []
        return result

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        results = VideosSearch(link, limit=1)
        for result in (await results.next())["result"]:
            title = result["title"]
            duration_min = result["duration"]
            vidid = result["id"]
            yturl = result["link"]
            thumbnail = result["thumbnails"][0]["url"].split("?")[0]
            performer = result["channel"]["name"] if "channel" in result and "name" in result["channel"] else "YouTube"
        track_details = {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
            "performer": performer
        }
        return track_details, vidid

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]

        cookie_file = cookie_txt_file()
        if not cookie_file:
            return [], link

        ytdl_opts = {"quiet": True, "cookiefile": cookie_file}
        ydl = yt_dlp.YoutubeDL(ytdl_opts)
        with ydl:
            formats_available = []
            r = ydl.extract_info(link, download=False)
            for format in r.get("formats", []):
                try:
                    fmtstr = str(format.get("format", ""))
                except:
                    continue
                if "dash" in fmtstr.lower():
                    continue
                try:
                    filesize = format.get("filesize")
                    fid = format.get("format_id")
                    ext = format.get("ext")
                    note = format.get("format_note")
                except:
                    continue
                formats_available.append(
                    {
                        "format": fmtstr,
                        "filesize": filesize,
                        "format_id": fid,
                        "ext": ext,
                        "format_note": note,
                        "yturl": link,
                    }
                )
        return formats_available, link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        a = VideosSearch(link, limit=10)
        result = (await a.next()).get("result")
        title = result[query_type]["title"]
        duration_min = result[query_type]["duration"]
        vidid = result[query_type]["id"]
        thumbnail = result[query_type]["thumbnails"][0]["url"].split("?")[0]
        return title, duration_min, thumbnail, vidid

    async def download(
        self,
        link: str,
        mystic,
        video: bool = False,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> Tuple[Union[str, str], bool]:
        if videoid:
            link = self.base + link
        loop = asyncio.get_running_loop()

        try:
            track_details, vidid = await self.track(link)
        except Exception as e:
            print(f"[FAIL] Could not get track details: {e}")
            return None, True

        # if not video and logger available, check DB for cached file_id (functionality in main bot)
        # We'll keep the same interface: return file_id (str) with False to indicate not local path
        # (Implementation of DB/cache is outside scope of this module)

        # Download
        if video:
            try:
                downloaded_file = await download_video(link)
            except Exception as e:
                print(f"[FAIL] download_video exception: {e}")
                downloaded_file = None
        else:
            downloaded_file = await download_song(link)

        if not downloaded_file:
            return None, True

        # if upload-to-log-channel required, main bot should handle it (we keep placeholder)
        return downloaded_file, True


# End of file
