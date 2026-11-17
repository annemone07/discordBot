import os
import json
import discord
from dotenv import load_dotenv
from discord.ext import commands
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
FOLDER_ID = "1M9W01ExFYSUcsPDhOtJxp7MU_7QDsSMTcRAu72fUWsKJNbtPiRMkANzDg6Hg5EiiwjhA7lyJ"

bot = discord.Bot()

created_threads = {}
THREADS_FILE = "created_threads.json"

closed_threads = {}
CLOSED_THREADS_FILE = "closed_threads.json"

if(os.path.exists(THREADS_FILE)):
    with open(THREADS_FILE, "r") as f:
        created_threads = json.load(f)
else:
    created_threads = {}
    
if(os.path.exists(THREADS_FILE)):
    with open(THREADS_FILE, "r") as f:
        closed_threads = json.load(f)
else:
    closed_threads = {}

def auth_google():
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
        token.write(creds.to_json())

def saveThreads():
    with open(THREADS_FILE, "w") as f:
        json.dump(created_threads, f)
    with open(CLOSED_THREADS_FILE, "w") as f:
        json.dump(closed_threads, f)

def getDrive():
    creds = None
    if(os.path.exists("token.json")):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            auth_google()
            creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return build("drive", "v3", credentials=creds)

@bot.command()
async def stop(context):
    role = discord.utils.get(context.guild.roles, name="owner")
    if not role:
        await context.respond("The specified role does not exist.")
        return
    if role not in context.author.roles:
        await context.respond("You do not have permission to stop the bot.")
        return
    await context.respond("Shutting down bot...")
    await bot.close()

@bot.command()
async def upload(context):
    try:
        await context.defer()

        service = getDrive()
        results = service.files().list(
            q=f"'{FOLDER_ID}' in parents",
            fields="files(id, name, owners(emailAddress))"
        ).execute()
        files = results.get("files", [])
        
        if not files:
            await context.followup.send("No files found in the specified folder.")
            return
        
        checkNewChannel = False
        
        role = discord.utils.get(context.guild.roles, name="owner")
        if not role:
            await context.followup.send("The specified role does not exist.")
            return
        
        for file in files:
            fileID = file["id"]
            ownerEmail = file["owners"][0]["emailAddress"]
            emailPrefix = ownerEmail.split("@")[0]
            fileName = emailPrefix            
            
            if fileID not in created_threads and fileID not in closed_threads:
                overwrites = {
                    context.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    role: discord.PermissionOverwrite(read_messages=True),
                    context.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                
                uniqueName = fileName
                counter=1
                while uniqueName in [channel.name for channel in context.guild.text_channels]:
                    uniqueName = f"{fileName}-{counter}"
                    counter += 1
                ticket = await context.guild.create_text_channel(
                    name=uniqueName,
                    overwrites=overwrites
                )
                created_threads[fileID] = ticket.id
                saveThreads()
                await ticket.send(f"Private channel created for {fileName}")
                checkNewChannel = True
                
                channel = discord.utils.get(context.guild.text_channels, name="general")
                if channel:
                    await channel.send(f"Private channel created for {fileName}: {ticket.mention}")
            else:
                await context.followup.send(f"Channel already exists for {fileName}.")
        
        if not checkNewChannel:
            await context.followup.send("All files already have channels.")
        else:
            await context.followup.send("Channels created successfully")
    except HttpError as error:
        await context.followup.send(f"An error occurred for drive: {error}")
    except Exception as e: #ver q erros ver dps
        await context.followup.send(f"An unexpected error occurred: {e}")
    
@bot.command()
async def close_ticket(context, name: str):
    await context.defer()
    
    role = discord.utils.get(context.guild.roles, name="owner")
    if not role:
        await context.followup.send("The specified role does not exist.")
        return
    if role not in context.author.roles:
        await context.followup.send("You do not have permission to close this ticket.")
        return

    channel = discord.utils.get(context.guild.text_channels, name=name)
    if not channel:
        await context.followup.send(f"No channel found with the name {name}.")
        return

    try:
        is_same_channel = (channel.id == context.channel.id)
        await channel.delete()

        for fileID, channelID in list(created_threads.items()):
            if channelID == channel.id:
                closed_threads[fileID] = created_threads[fileID]
                del created_threads[fileID]
                saveThreads()
                break

        if not is_same_channel:
            await context.followup.send(f"Channel {name} has been deleted.")

    except Exception as error: #ver q erros ver dps
        if context.guild.get_channel(context.channel.id):
            await context.followup.send(f"An error occurred while trying to delete the channel: {error}")
    
@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online")

bot.run(TOKEN)