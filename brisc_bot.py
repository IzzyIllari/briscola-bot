#--------------------IMPORTS--------------------#
import discord
import json
import sys
import sqlite3
import os
import os.path
from os import path
from datetime import datetime as dt
from discord.ext import commands

#--------------------SET UP--------------------#

# prefixes
def get_prefix(client, message):

    prefixes = ["briscola ", "b "] #prefixes

    # user can @mention the bot instead of using a prefix to execute a command
    return commands.when_mentioned_or(*prefixes)(client, message)

# token
TOKEN = "NzUxMTYyMjc4NDU1Mjc5NjU2.X1FEYw.Np8uHBDrSZBSVDy-VzYviH9MIDc"

# create the bot
bot = commands.Bot(
    command_prefix = get_prefix,                # prefix
    description = "A bot to play briscola",     # bot description
    owner_id = 299001806745370624,              # user ID
    case_insensitive = True                     # case-insensitive commands 
)
bot.remove_command("help")
#os.chdir(r"/Users/iillari/Documents/briscolla_bot")
#print(os.getcwd())

#--------------------MEMBER CLASS--------------------#

class Member:
    # constructor and attributes
    def __init__(self, identity, name, color=0xd40000, exp=0, lvl=1, totGames=0, wins=0, losses=0, ties=0):
        self.identity = identity
        self.name = name
        self.color = color
        self.exp = exp
        self.lvl = lvl
        self.totGames = totGames
        self.wins = wins
        self.losses = losses
        self.ties = ties
        
    # methods
    def fetchMember(self):
        memberInfo = (self.identity, self.name, self.color, self.exp, self.lvl, self.totGames, self.wins, self.losses, self.ties)
        return memberInfo
    
    def fetchMemberExpLvl(self):
        memberInfo = (self.identity, self.name, self.color, self.exp, self.lvl)
        return memberInfo
    
    def fetchMemberGames(self):
        memberInfo = (self.totGames, self.name, self.color, self.wins, self.losses, self.ties)
        return memberInfo
    
    def getColor(self):
        colorInfo = (self.color)
        return colorInfo
    
    def setName(self, n):
        self.name = n

    def setColor(self, c):
        self.color = c

    def setExp(self, e):
        self.exp = e
    
    def setLvl(self, l):
        self.lvl = l
    
    def setTotGames(self, t):
        self.totGames = t
    
    def setWins(self, w):
        self.wins = w
    
    def setLosses(self, ls):
        self.losses = ls
    
    def setTies(self, ts):
        self.ties = ts

#--------------------COMMANDS--------------------#

# simple ping command
@bot.command()
async def ping(ctx):
    await ctx.send(f'Pong! {round(bot.latency * 1000)}ms')

# simple hello command
@bot.command(
    name = "hello", 
    aliases = ["h"], 
    help = "Simple hello message that provides lag info."
    )
async def hello_command(ctx):
    start = dt.timestamp(dt.now()) #start timestamp
    msg = await ctx.send(content = "Waving...") #pinging has started
    await msg.edit(content=f"Hello!\nOne message round-trip took { round((dt.timestamp( dt.now() ) - start) * 1000, 2) }ms.")
    return

# info menu
@bot.command(
    name="help", 
    aliases=["info", "menu", "about"], 
    help = "Find out everything you need to know.")
async def help(ctx):
    embed = discord.Embed(title="Commands available for the Briscola Bot", 
        description="For more help with a command run: `briscola help [command]`", 
        color = 0xd40000)
    embed.add_field(name="`info`", value="Info about the bot.", inline=True)
    embed.add_field(name="`tutorial`", value="Step-by-step tutorial.", inline=True)
    embed.add_field(name="`rules`", value="List of rules.", inline=True)
    embed.add_field(name="`play`", value="Play a game of briscola.", inline=True)
    embed.add_field(name="`make_database`", value="Create the database where server members will be stored.", inline=True)
    embed.add_field(name="`check_rank`", value="Check your EXP & LVL.", inline=True)
    embed.add_field(name="`add`", value="Add a member to the database.", inline=True)
    embed.add_field(name="`change_color`", value="Change the color of your EXP/LVL message.", inline=True)
    now = dt.now()
    timeOut = now.strftime("%A %d %b %Y %I:%M:%S %p")
    embed.set_footer(text = f"Requested by {ctx.message.author.name} on {timeOut}", icon_url = ctx.message.author.avatar_url)
    await ctx.send(embed=embed)


# create the database
@bot.command(
    name = "make_database", 
    aliases = ["make_db", "mdb"], 
    help = "Create the database where server members will be stored."
    )
async def make_database(ctx):
    serverNameRaw = ctx.message.guild.name
    serverName = serverNameRaw.replace(' ', '') + '.db' 
    # SQLite database for storing members on disk
    # creates database in same dir as .py
    db = None
    if path.exists(f"{serverNameRaw}.db") != True:
        db = sqlite3.connect(serverName)
        await ctx.send(f"{serverNameRaw} database created!")
    else:
        db = sqlite3.connect(serverName)
        await ctx.send(f"{serverNameRaw} database already exists.")
    #call the database and execute SQL statements
    try:
        db.execute('create table members (m_id int, m_name text, m_color int, m_exp int, m_lvl int, m_tot_games int, m_wins int, m_losses int, m_ties int)')
        await ctx.send("Table of members created!")
    except:
        pass
    return

# check the exp & lvl of the message author
@bot.command(
    name = "check_rank", 
    aliases = ["rank", "r", "cr"], 
    help = "Check the exp & lvl of message author."
    )
async def check_rank(ctx):
    storage = [] # empty list for storing the member objects in memory 
    serverNameRaw = ctx.message.guild.name
    serverName = serverNameRaw.replace(' ', '') + '.db'
    #check if database exists
    if path.exists(f"{serverNameRaw}.db") != True:
        await ctx.send(f"{serverNameRaw} database does not exist!\nCreate database first.")
        return
    else:
        db = sqlite3.connect(serverName)
        #await ctx.send(f"{serverNameRaw} database exists.")
        # store all member objects in memory
        try:
            cursor = db.execute('select * from members')
            for row in cursor:
                mId = row[0]
                mName = row[1]
                mColor = row[2]
                mExp = row[3]
                mLvl = row[4]
                mTotGames = row[5]
                mWins = row[6]
                mLosses = row[7]
                mTies = row[8]
                newMember = Member(mId, mName, mColor, mExp, mLvl, mTotGames, mWins, mLosses, mTies)
                storage.append(newMember)
        except:
            pass
        # print message author
        memberName = ctx.message.author
        memberID = memberName.id
        #await ctx.send(f"The author of this message is {memberName} and their ID is {memberID}.")
        # check if message author's ID appears in the members list
        found = False
        for s in storage:
            if s.fetchMember()[0] == memberID:
                found = True
                #await ctx.send(f"There is a member with ID {memberID}: {found}")
                memberInfo = s.fetchMemberExpLvl()
                embed = discord.Embed(title=f"Rank of @{memberInfo[1]}", color = memberInfo[2])
                embed.set_thumbnail(url = ctx.message.author.avatar_url)
                embed.add_field(name="`Level:`", value = memberInfo[4], inline = True)
                embed.add_field(name="`Experience:`", value = memberInfo[3], inline = True)
                now = dt.now()
                timeOut = now.strftime("%A %d %b %Y %I:%M:%S %p")
                embed.set_footer(text = f"{timeOut}")
                await ctx.send(embed=embed)
                #await ctx.send(s.fetchMemberExpLvl())
                return s
        if found == False:
            await ctx.send("There is no member with that ID in the database.")
            return False
        return

# add a member
@bot.command(
    name = "add", 
    aliases = ["a"], 
    help = "Add a member to the database"
    )
async def add(ctx):
    storage = [] # empty list for storing the member objects in memory 
    serverNameRaw = ctx.message.guild.name
    serverName = serverNameRaw.replace(' ', '') + '.db'
    if path.exists(f"{serverNameRaw}.db") != True:
        await ctx.send(f"{serverNameRaw} database does not exist!\nCreate database first.")
        return
    else:
        db = sqlite3.connect(serverName)
        await ctx.send(f"{serverNameRaw} database exists.")
        try:
            cursor = db.execute('select * from members')
            for row in cursor:
                mId = row[0]
                mName = row[1]
                mColor = row[2]
                mExp = row[3]
                mLvl = row[4]
                mTotGames = row[5]
                mWins = row[6]
                mLosses = row[7]
                mTies = row[8]
                newMember = Member(mId, mName, mColor, mExp, mLvl, mTotGames, mWins, mLosses, mTies)
                storage.append(newMember)
        except:
            pass
        #memberName = ctx.message.author.name
        memberName = str(ctx.message.author)
        memberID = ctx.message.author.id
        #await ctx.send(f"The author of this message is {memberName} and their ID is {memberID}.")
        #create the member object, add it to the storage list and the db database
        newMember = Member(memberID, memberName)
        type_ID = type(memberID)
        type_Name = type(memberName)
        #await ctx.send(f"Type of ID is {type_ID} and type of name is {type_Name}.")
        storage.append(newMember)
        temp = newMember.fetchMember()
        db.execute('insert into members (m_id, m_name, m_color, m_exp, m_lvl, m_tot_games, m_wins, m_losses, m_ties) values (?, ?, ?, ?, ?, ?, ?, ?, ?)', temp)
        db.commit()
        await ctx.send('Member added successfully')
        return

# info menu
@bot.command(
    name="change_color", 
    aliases=["cc", "change", "color"], 
    help = "Change the color of your EXP/LVL message.")
async def change_color(ctx):
    memberID = ctx.message.author.id
    found = False
    storage = [] #empty list for storing the student objects in memory
    serverNameRaw = ctx.message.guild.name
    serverName = serverNameRaw.replace(' ', '') + '.db'
    db = sqlite3.connect(serverName)
    try:
        cursor = db.execute('select * from members')
        for row in cursor:
                mId = row[0]
                mName = row[1]
                mColor = row[2]
                mExp = row[3]
                mLvl = row[4]
                mTotGames = row[5]
                mWins = row[6]
                mLosses = row[7]
                mTies = row[8]
                newMember = Member(mId, mName, mColor, mExp, mLvl, mTotGames, mWins, mLosses, mTies)
                storage.append(newMember)
    except:
        pass

    for s in storage:
        if s.fetchMember()[0] == mId:
            found = True
            colorCurrent = str(hex(s.getColor()))
            colorHex = colorCurrent.replace("0x", "#")
            await ctx.send(f"Current color is: {colorHex}.")
            await ctx.send("To change the color please input ")
            return s
    if found == False:
        await ctx.send('No member by that Id')
        return False

#--------------------FINISH--------------------#

# print to screen when the bot is up and running
@bot.event
async def on_ready():
    print("Bot is running.")
    # name and ID of the bot
    print(f'Logged in as {bot.user.name} Bot #{bot.user.id}.')  
    #print("\nGo here to have your bot join your server: ")
    #print("\nhttps://discord.com/api/oauth2/authorize?bot_id=751162278455279656&permissions=8&scope=bot")
    return

# run with the token
bot.run(TOKEN, bot = True, reconnect = True)