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

# Global Config State
rmp_config = {
    "rmp_channel_id": None,
    "seen_reviews": []
}

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

def load_config():
    global rmp_config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                rmp_config = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

def save_config():
    try:
        # Trim seen_reviews to keep file size manageable
        if len(rmp_config['seen_reviews']) > 50:
            rmp_config['seen_reviews'] = rmp_config['seen_reviews'][-50:]

        with open(CONFIG_FILE, 'w') as f:
            json.dump(rmp_config, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

# Load config on startup
load_config()

# --- RMP Logic ---

async def post_review(channel, review, professor_name):
    embed = discord.Embed(
        title=f"New Review for {professor_name}",
        description=review.get('comment', 'No comment provided.'),
        color=discord.Color.red() if review.get('ratingTags') and "Tough grader" in review.get('ratingTags') else discord.Color.green()
    )

    # Fields
    embed.add_field(name="Class", value=review.get('class', 'N/A'), inline=True)
    embed.add_field(name="Date", value=review.get('date', 'N/A'), inline=True)
    embed.add_field(name="Grade", value=review.get('grade', 'N/A'), inline=True)

    # Ratings
    difficulty = review.get('difficultyRating', 'N/A')
    embed.add_field(name="Difficulty", value=f"{difficulty}/5", inline=True)

    attendance = review.get('attendanceMandatory', 'N/A')
    embed.add_field(name="Attendance", value=attendance, inline=True)

    take_again = review.get('wouldTakeAgain', 'N/A')
    embed.add_field(name="Take Again", value="Yes" if take_again else "No", inline=True)

    tags = review.get('ratingTags', '')
    if tags:
        embed.add_field(name="Tags", value=tags, inline=False)

    embed.set_footer(text=f"Review ID: {review.get('id')}")

    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        logger.error(f"Failed to send message to channel {channel.id}: Forbidden")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

@tasks.loop(minutes=10)
async def check_rmp_updates():
    channel_id = rmp_config.get("rmp_channel_id")
    if not channel_id:
        return

    # Wait until bot is ready if this runs immediately on start
    await bot.wait_until_ready()

    channel = bot.get_channel(channel_id)
    if not channel:
        logger.error(f"Channel with ID {channel_id} not found.")
        return

    logger.info("Checking for RMP updates...")

    # Fetch details for name
    try:
        details = rmp_helper.get_professor_details()
        prof_name = f"{details['firstName']} {details['lastName']}" if details else "Unknown Professor"

        # Fetch all reviews (fetching a larger number to ensure we get new ones, assuming < 100 total for now or pagination needed)
        # The helper defaults to 10, let's ask for 20 to be safe for updates.
        reviews = rmp_helper.get_reviews(count=20)

        if not reviews:
            return

        # Process reviews from oldest to newest
        # The API returns newest first usually, so we reverse
        reviews.reverse()

        new_reviews_found = False

        for review in reviews:
            rid = review.get('id')
            if rid not in rmp_config['seen_reviews']:
                logger.info(f"New review found: {rid}")
                await post_review(channel, review, prof_name)
                rmp_config['seen_reviews'].append(rid)
                new_reviews_found = True
                # Add a small delay to avoid rate limits or spamming
                await asyncio.sleep(1)

        if new_reviews_found:
            save_config()

    except Exception as e:
        logger.error(f"Error in check_rmp_updates: {e}")

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

# --- RMP Commands ---

@bot.tree.command(name="rmsanrr", description="开始监控 RateMyProfessor 评价 (将清除历史记录)")
@app_commands.default_permissions(administrator=True)
async def start_rmp(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    rmp_config['rmp_channel_id'] = channel_id
    rmp_config['seen_reviews'] = [] # Reset history to force backfill
    save_config()

    await interaction.response.send_message(f"已在当前频道 (<#{channel_id}>) 开启 RateMyProfessor 监控。历史记录已清除，即将开始回填。", ephemeral=True)

    # Trigger update immediately
    if not check_rmp_updates.is_running():
        check_rmp_updates.start()
    else:
        # Restarting to trigger immediately
        check_rmp_updates.restart()

@bot.tree.command(name="byebyesanrr", description="停止监控 RateMyProfessor 评价")
@app_commands.default_permissions(administrator=True)
async def stop_rmp(interaction: discord.Interaction):
    rmp_config['rmp_channel_id'] = None
    save_config()
    await interaction.response.send_message("已停止 RateMyProfessor 监控。", ephemeral=True)

@bot.tree.command(name="force_rmp_check", description="强制检查 RateMyProfessor 更新")
@app_commands.default_permissions(administrator=True)
async def force_rmp(interaction: discord.Interaction):
    await interaction.response.send_message("正在强制检查更新...", ephemeral=True)
    # Restarting the task is the easiest way to force a run now.
    check_rmp_updates.restart()

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
