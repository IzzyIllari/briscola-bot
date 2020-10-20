# imports
import discord
import json
import os
from discord.ext import commands

# set up
TOKEN = "NzUxMTYyMjc4NDU1Mjc5NjU2.X1FEYw.Np8uHBDrSZBSVDy-VzYviH9MIDc"
client = commands.Bot(command_prefix=commands.when_mentioned_or("briscola "))
#client = commands.Bot(command_prefix = 'briscola ')
os.chdir(r"/Users/iillari/Documents/briscolla_bot")

# print to screen when the bot is up and running
@client.event
async def on_ready():
#    await client.change_presence(status=discord.Status.idle)
    print("Bot is running.")
    print("\nGo here to have your bot join your server: ")
    print("\nhttps://discord.com/api/oauth2/authorize?client_id=751162278455279656&permissions=8&scope=bot")

# help menu
@client.event
async def on_message(message):
    # help menu
    if message.content.startswith('briscola help'):
        embed = discord.Embed(title="Commands available for the Briscola Bot", description="For more help with a command run: `briscola help [command]`", color=0xd40000)
        embed.add_field(name="`about`", value="Info about the bot.", inline=False)
        embed.add_field(name="`tutorial`", value="Step-by-step tutorial.", inline=True)
        embed.add_field(name="`rules`", value="List of rules.", inline=True)
        embed.add_field(name="`play`", value="Play a game of briscola.", inline=True)
        embed.set_footer(text="foot")
        await message.channel.send(embed=embed)
    # update json whenever member sends a message
    with open("users.json", "r") as f:
        users = json.load(f)
    
    await update_data(users, message.author)
    await add_experience(users, message.author, 1)
    await level_up(users, message.author, message.channel)

    with open("users.json", "w") as f:
        json.dump(users, f)


# simple ping command
@client.command()
async def ping(ctx):
    await ctx.send(f'Pong! {round(client.latency * 1000)}ms')

# simple hello command    
@client.command(aliases=['hello'])
async def _hello(ctx):
    await ctx.send(f'Hello! {round(client.latency * 1000)}ms')

# update the json file whenever a new member joins
@client.event
async def on_member_join(member):
    with open("users.json", "r") as f:
        users = json.load(f)
    
    await update_data(users, member)

    with open("users.json", "w") as f:
        json.dump(users, f)

# helper functions

# update
async def update_data(users, user):
    if not user.id in users:
        users[user.id] = {}
        users[user.id]["experience"] = 0
        users[user.id]["level"] = 1

# experience
async def add_experience(users, user, exp):
    users[user.id]["experience"] += exp

# level up
async def level_up(users, user, channel):
    experience = users[user.id]["experience"]
    lvl_start = users[user.id]["level"]
    # formula to calculate levels
    lvl_end = int(experience ** (1/4)) 

    if lvl_start < lvl_end:
        await client.send_message(channel, "{} has leveled up to level {}".format(user.mention, lvl_end))
        users[user.id]["level"] = lvl_end


# run with the token
client.run(TOKEN)