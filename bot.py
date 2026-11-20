import os
import sys
import re
import json
from io import BytesIO
import asyncio
import subprocess
import random
import discord
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

shouldRestart = False

MB_SIZE = 1024 * 1024

NAME_INDEX = 1
USERNAME_INDEX = 2
FILE_INDEX = 3

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "12C6eL9FZYLjjYAY8Tz39fBQbBlUfnfsi_z9rxAU6V_Y")
SHEET_RANGE = os.getenv("SHEET_RANGE", "Respostas ao formulário 1!A2:Z")

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",  
    ]
FOLDER_ID = "1uzsXXVS-GqwIO9jlwIqcr7B2ybe0TnPJ"

bot = discord.Bot()

createdThreads = {}
THREADS_FILE = "created_threads.json"

closedThreads = {}
CLOSED_THREADS_FILE = "closed_threads.json"

ALLOWED_ROLES = ("owner",)
ADMIN_CHANNELS = ("general",)

if(os.path.exists(THREADS_FILE)):
    with open(THREADS_FILE, "r") as f:
        createdThreads = json.load(f)
else:
    createdThreads = {}
    
if(os.path.exists(CLOSED_THREADS_FILE)):
    with open(CLOSED_THREADS_FILE, "r") as f:
        closedThreads = json.load(f)
else:
    closedThreads = {}

def auth_google():
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
        token.write(creds.to_json())

def saveThreads():
    with open(THREADS_FILE, "w") as f:
        json.dump(createdThreads, f)
    with open(CLOSED_THREADS_FILE, "w") as f:
        json.dump(closedThreads, f)

def getCreds():
    creds = None
    if(os.path.exists("token.json")):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            auth_google()
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return creds

def getSheets():
    return build("sheets", "v4", credentials=getCreds())

def getDrive():
    return build("drive", "v3", credentials=getCreds())

def extractDriveFileId(url: str) -> str | None:
    if not url:
        return None
    patterns = [
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"[?&]id=([a-zA-Z0-9_-]+)",
        r"/open\?id=([a-zA-Z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def cleanChannelName(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", name.strip().lower()).strip("-")
    cleaned = re.sub(r"-+", "-", cleaned)
    return (cleaned or "ticket")[:90]


def downloadDriveFile(driveService, driveFileId: str) -> bytes:
    request = driveService.files().get_media(fileId=driveFileId)
    buffer = BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer.read()

def find_guild_member(guild: discord.Guild, rawUsername: str) -> discord.Member | None:
    if not rawUsername:
        return None
    target = rawUsername.strip().lstrip("@").lower()
    for member in guild.members:
        candidates = [
            member.name,
            member.global_name,
            member.display_name,
        ]
        if any(c and c.lower() == target for c in candidates):
            return member
    return None

def getMatchingRoles(guild: discord.Guild, roleNames: tuple[str, ...] | list[str]) -> list[discord.Role]:
    targets = {name.lower() for name in roleNames}
    return [role for role in guild.roles if role.name.lower() in targets]


def hasRoleIn(member: discord.Member, roleNames: tuple[str, ...] | list[str]) -> bool:
    targets = {name.lower() for name in roleNames}
    return any(role.name.lower() in targets for role in member.roles)


def getMatchingChannels(guild: discord.Guild, channelNames: tuple[str, ...] | list[str]) -> list[discord.TextChannel]:
    targets = {name.lower() for name in channelNames}
    return [ch for ch in guild.text_channels if ch.name.lower() in targets]

@bot.command()
async def stop(context):
    global shouldRestart
    allowedRoles = getMatchingRoles(context.guild, ALLOWED_ROLES)
    if not allowedRoles:
        await context.respond("this role doesn't exist")
        return
    if not hasRoleIn(context.author, ALLOWED_ROLES):
        await context.respond("you don't have permission to do that")
        return

    shouldRestart = False
    await context.respond("shutting... down...")

    for task in asyncio.all_tasks(asyncio.get_running_loop()):
        if task is not asyncio.current_task():
            task.cancel()

@bot.command()
async def restart(context):
    global shouldRestart
    allowedRoles = getMatchingRoles(context.guild, ALLOWED_ROLES)
    if not allowedRoles:
        await context.respond("this role doesn't exist")
        return
    if not hasRoleIn(context.author, ALLOWED_ROLES):
        await context.respond("you don't have permission to do that")
        return

    shouldRestart = True
    await context.respond("Restarting bot...")

    for task in asyncio.all_tasks(asyncio.get_running_loop()):
        if task is not asyncio.current_task():
            task.cancel()

@bot.command()
async def close_ticket(context, name: str):
    await context.defer()
    
    allowedRoles=getMatchingRoles(context.guild, ALLOWED_ROLES)
    if not allowedRoles:
        await context.respond("this role doesn't exist")
        return
    if not hasRoleIn(context.author, ALLOWED_ROLES):
        await context.respond("you don't have permission to do that")
        return

    channel = discord.utils.get(context.guild.text_channels, name=name)
    if not channel:
        await context.followup.send(f"no channel found with the name {name}.")
        return

    try:
        isSameChannel = (channel.id == context.channel.id)
        await channel.delete()

        for fileID, channelID in list(createdThreads.items()):
            if channelID == channel.id:
                closedThreads[fileID] = createdThreads[fileID]
                del createdThreads[fileID]
                saveThreads()
                break

        if not isSameChannel:
            await context.followup.send(f"channel {name} has been deleted.")

    except Exception as error: #ver q erros ver dps
        if context.guild.get_channel(context.channel.id):
            await context.followup.send(f"an error occurred while trying to delete the channel: {error}")

@bot.command()
async def upload(context):
    try:
        await context.defer()

        allowedRoles=getMatchingRoles(context.guild, ALLOWED_ROLES)
        if not allowedRoles:
            await context.respond("this role doesn't exist")
            return
        if not hasRoleIn(context.author, ALLOWED_ROLES):
            await context.respond("you don't have permission to do that")
            return

        sheetsService = getSheets()
        driveService = getDrive()

        result = (
            sheetsService.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, 
                range=SHEET_RANGE
            ).execute()
        )
        rows = result.get("values", [])

        if not rows:
            await context.followup.send("no responses found in the spreadsheet.")
            return

        checkNewChannel = False
        existingNames = {channel.name for channel in context.guild.text_channels}

        for idx, row in enumerate(rows):
            field1 = row[NAME_INDEX].strip() if len(row) > NAME_INDEX else f"submission-{idx + 2}"
            fileLink = row[FILE_INDEX].strip() if len(row) > FILE_INDEX else ""
            targetUsername = row[USERNAME_INDEX].strip() if len(row) > USERNAME_INDEX else ""
            targetMember = find_guild_member(context.guild, targetUsername)

            submissionId = f"{field1}"
            if submissionId in createdThreads or submissionId in closedThreads:
                continue

            overwrites = {
                context.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                context.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            for r in allowedRoles:
                overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            if targetMember:
                overwrites[targetMember] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

            baseName = cleanChannelName(field1)
            uniqueName = baseName
            counter = 1
            while uniqueName in existingNames:
                uniqueName = f"{baseName[:85]}-{counter}"
                counter += 1

            ticket = await context.guild.create_text_channel(
                name=uniqueName,
                overwrites=overwrites,
            )
            existingNames.add(ticket.name)
            createdThreads[submissionId] = ticket.id
            saveThreads()
            checkNewChannel = True

            rolesMention = ", ".join(r.mention for r in allowedRoles)
            if targetMember:
                await ticket.send(
                    f"private channel created for **{field1}** ({targetMember.mention} & {rolesMention})."
                )
            else:
                await ticket.send(
                    f"private channel created for **{field1}** ({rolesMention}). *(Could not find Discord user `{targetUsername}` in this server.)*"
                )

            driveFileId = extractDriveFileId(fileLink)
            if not driveFileId:
                await ticket.send(
                    f"no valid Google Drive file link found in field 4 (`{fileLink or 'empty'}`)."
                )
            else:
                meta = (
                    driveService.files().get(fileId=driveFileId, fields="id, name, size, webViewLink").execute()
                )
                driveName = meta.get("name", "attachment")
                fileSize = int(meta.get("size", 0))
                webLink = meta.get("webViewLink") or fileLink

                if fileSize <= 20*MB_SIZE:
                    fileData = downloadDriveFile(driveService, driveFileId)
                    await ticket.send(
                        content=f"attachment ('{driveName}', {fileSize / MB_SIZE:.2f} MB):",
                        file=discord.File(BytesIO(fileData), filename=driveName),
                    )
                else:
                    embed = discord.Embed(
                        title=driveName,
                        description=f"file is larger than 20 MB ({fileSize / MB_SIZE:.2f} MB). view it in Google Drive.",
                        url=webLink,
                    )
                    await ticket.send(embed=embed)

            adminChannel = discord.utils.get(context.guild.text_channels, name=ADMIN_CHANNELS)
            if adminChannel:
                await adminChannel.send(
                    f"private channel created for **{field1}**: {ticket.mention}"
                )

        if not checkNewChannel:
            await context.followup.send("all submissions already have channels. yeah")
        else:
            await context.followup.send("channels created successfully.")

    except HttpError as error:
        await context.followup.send(f"a google api error occurred: {error}")
    except Exception as e:
        await context.followup.send(f"an unexpected error occurred: {e}")
    
@bot.event
async def on_ready():
    if(random.randint(1, 1000) == 1000):
        print(f"i'm different")
    print(f"{bot.user} is ready and online")

if __name__ == "__main__":
    try:
        bot.run(TOKEN)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if shouldRestart:
            subprocess.Popen([sys.executable, *sys.argv])