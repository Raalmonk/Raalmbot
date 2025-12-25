#!/usr/bin/env python3
import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import json
import os
import asyncio
import logging
from dotenv import load_dotenv
from rmp_helper import RMPHelper
from datetime import datetime

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 1. Load .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 2. Intents
intents = discord.Intents.default()
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

# RMP Constants
PROFESSOR_ID = 2635703
CONFIG_FILE = 'config.json'

# Initialize RMP Helper
rmp_helper = RMPHelper(PROFESSOR_ID)

# --- Helper Functions ---

def load_responses():
    try:
        with open('responses.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return ["错误：找不到 responses.json 文件！"]

def load_fortunes():
    try:
        with open('fortunes.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return ["错误：找不到 fortunes.json 文件！"]

@bot.event
async def on_ready():
    logger.info(f'RaalmBot 已上线: {bot.user} (ID: {bot.user.id})')

    # Start the loop if not already running
    if not check_rmp_updates.is_running():
        check_rmp_updates.start()

@bot.tree.command(name="wsnd", description="随机抽取一条回复")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def wsnd(interaction: discord.Interaction):
    options = load_responses()
    selected = random.choice(options)
    await interaction.response.send_message(selected)

@bot.tree.command(name="抽一签", description="想你了m萨")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def draw_lot(interaction: discord.Interaction):
    fortunes = load_fortunes()
    selected = random.choice(fortunes)
    await interaction.response.send_message(selected)

# --- 4. 同步指令 (管理员专用) ---
@bot.command()
async def sync(ctx):
    print("正在同步指令...")
    fmt = await ctx.bot.tree.sync()
    await ctx.send(f"同步完成！共同步了 {len(fmt)} 个指令。")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("错误：未在 .env 文件中找到 Token。")