
from AbhiXMusic.core.bot import Abhi
from AbhiXMusic.core.dir import dirr
from AbhiXMusic.core.git import git
from AbhiXMusic.core.userbot import Userbot
from AbhiXMusic.misc import dbb, heroku
from SafoneAPI import SafoneAPI
from .logging import LOGGER

dirr()
git()
dbb()
heroku()

app = Abhi()
userbot = Userbot()
api = SafoneAPI()

from .platforms import *

Apple = AppleAPI()
Carbon = CarbonAPI()
SoundCloud = SoundAPI()
Spotify = SpotifyAPI()
Resso = RessoAPI()
Telegram = TeleAPI()
YouTube = YouTubeAPI()

APP = "InflexOwnerBot"  # connect music api key "Dont change it"