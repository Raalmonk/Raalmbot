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
from datetime import datetime, timedelta, timezone

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
LOG_FILE = 'message_logs.json'

# Initialize RMP Helper
rmp_helper = RMPHelper(PROFESSOR_ID)

# Global Config State
rmp_config = {
    "rmp_channel_ids": [],
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
                data = json.load(f)

                # Migration: Convert old single channel_id to list
                if "rmp_channel_id" in data:
                    cid = data.pop("rmp_channel_id")
                    if cid:
                        data.setdefault("rmp_channel_ids", [])
                        if cid not in data["rmp_channel_ids"]:
                            data["rmp_channel_ids"].append(cid)

                rmp_config.update(data)

                # Ensure rmp_channel_ids exists
                if "rmp_channel_ids" not in rmp_config:
                    rmp_config["rmp_channel_ids"] = []

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

def log_message(content, channel_name, requester):
    """Logs a message sent by the bot."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "content": content[:200], # Store first 200 chars to avoid huge logs
        "channel": str(channel_name),
        "requester": str(requester)
    }

    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8') as f:
                try:
                    logs = json.load(f)
                except json.JSONDecodeError:
                    logs = []

        logs.append(entry)

        # Keep last 1000 logs locally
        if len(logs) > 1000:
            logs = logs[-1000:]

        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs, f, indent=2, ensure_ascii=False)

    except Exception as e:
        logger.error(f"Failed to write log: {e}")

# Load config on startup
load_config()

# --- RMP Logic ---

async def post_review(channel, review, professor_name, requester="Auto"):
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
        # Log the message
        log_message(f"RMP Review ID: {review.get('id')}", channel.name, requester)
    except discord.Forbidden:
        logger.error(f"Failed to send message to channel {channel.id}: Forbidden")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

@tasks.loop(minutes=10)
async def check_rmp_updates():
    channel_ids = rmp_config.get("rmp_channel_ids", [])
    if not channel_ids:
        return

    # Wait until bot is ready if this runs immediately on start
    await bot.wait_until_ready()

    logger.info("Checking for RMP updates...")

    # Fetch details for name
    try:
        details = rmp_helper.get_professor_details()
        prof_name = f"{details['firstName']} {details['lastName']}" if details else "Unknown Professor"

        # Fetch all reviews (fetching a larger number to ensure we get new ones)
        reviews = rmp_helper.get_reviews(count=20)

        if not reviews:
            return

        # Process reviews from oldest to newest
        reviews.reverse()

        new_reviews_found = False

        # Identify which reviews are new globally
        reviews_to_post = []
        for review in reviews:
            rid = review.get('id')
            if rid not in rmp_config['seen_reviews']:
                reviews_to_post.append(review)
                rmp_config['seen_reviews'].append(rid)
                new_reviews_found = True

        # Post new reviews to ALL subscribed channels
        if reviews_to_post:
            for channel_id in channel_ids:
                channel = bot.get_channel(channel_id)
                if channel:
                    for review in reviews_to_post:
                        logger.info(f"Posting review {review.get('id')} to channel {channel.name}")
                        await post_review(channel, review, prof_name, requester="Auto")
                        await asyncio.sleep(1) # Delay between messages
                else:
                    logger.warning(f"Channel ID {channel_id} not found/accessible.")

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

@bot.event
async def on_message(message):
    # Log bot's own messages if not already logged via post_review or commands
    if message.author == bot.user:
        # Check if we already logged this? It's hard to deduplicate perfectly without context ID.
        # But for general messages (like error messages, or direct replies not via slash commands helper), we can log here.
        # However, post_review logs explicitly. Commands log explicitly (we will add).
        # To avoid double logging, we might want to skip here if we cover all bases,
        # OR rely solely on on_message for general logging.
        # Given the "requester" requirement, explicit logging in commands is better.
        # But for "output self recent sent 100 messages", catching everything here is safer.
        # Let's try to detect if it was already logged? No, too complex.
        # Simplest approach: Log here with requester="Self/Unknown" if not called from a known logger.
        # But for now, let's rely on explicit logging in functions to capture "requester".
        pass

    await bot.process_commands(message)

@bot.tree.command(name="wsnd", description="随机抽取一条回复")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def wsnd(interaction: discord.Interaction):
    options = load_responses()
    selected = random.choice(options)
    await interaction.response.send_message(selected)
    log_message(selected, interaction.channel.name if interaction.channel else "DM", interaction.user.name)

@bot.tree.command(name="抽一签", description="想你了m萨")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def draw_lot(interaction: discord.Interaction):
    fortunes = load_fortunes()
    selected = random.choice(fortunes)
    await interaction.response.send_message(selected)
    log_message(selected, interaction.channel.name if interaction.channel else "DM", interaction.user.name)

# --- RMP Commands ---

@bot.tree.command(name="rmpstatus", description="查看当前自动获取 sanrr 评价的频道")
async def rmp_status(interaction: discord.Interaction):
    ids = rmp_config.get("rmp_channel_ids", [])
    if not ids:
        await interaction.response.send_message("目前没有在任何频道自动获取 sanrr 评价。")
        return

    channels_list = []
    for cid in ids:
        ch = bot.get_channel(cid)
        if ch:
            channels_list.append(f"{ch.name} (ID: {cid})")
        else:
            channels_list.append(f"Unknown Channel (ID: {cid})")

    msg = "正在以下频道自动获取 sanrr 评价:\n" + "\n".join(channels_list)
    await interaction.response.send_message(msg)
    log_message(msg, interaction.channel.name, interaction.user.name)


@bot.tree.command(name="rmsanrr", description="添加当前频道到 RateMyProfessor 监控列表")
@app_commands.default_permissions(administrator=True)
async def start_rmp(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in rmp_config['rmp_channel_ids']:
        rmp_config['rmp_channel_ids'].append(channel_id)
        save_config()
        msg = f"已将当前频道 (<#{channel_id}>) 添加到 RateMyProfessor 监控列表。"
        await interaction.response.send_message(msg)
        log_message(msg, interaction.channel.name, interaction.user.name)
    else:
        msg = "当前频道已在监控列表中。"
        await interaction.response.send_message(msg, ephemeral=True)
        log_message(msg, interaction.channel.name, interaction.user.name)

    # Trigger update immediately
    if not check_rmp_updates.is_running():
        check_rmp_updates.start()

@bot.tree.command(name="byebyesanrr", description="从 RateMyProfessor 监控列表中移除当前频道")
@app_commands.default_permissions(administrator=True)
async def stop_rmp(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id in rmp_config['rmp_channel_ids']:
        rmp_config['rmp_channel_ids'].remove(channel_id)
        save_config()
        msg = "已停止当前频道的 RateMyProfessor 监控。"
        await interaction.response.send_message(msg)
        log_message(msg, interaction.channel.name, interaction.user.name)
    else:
        await interaction.response.send_message("当前频道不在监控列表中。", ephemeral=True)

@bot.tree.command(name="force_rmp_check", description="强制检查 RateMyProfessor 更新")
@app_commands.default_permissions(administrator=True)
async def force_rmp(interaction: discord.Interaction):
    await interaction.response.send_message("正在强制检查更新...", ephemeral=True)
    log_message("Force RMP Check triggered", interaction.channel.name, interaction.user.name)
    check_rmp_updates.restart()

@bot.tree.command(name="mynewsanrr", description="检查最近5天的评价并补发")
async def my_new_sanrr(interaction: discord.Interaction):
    await interaction.response.defer() # Long running task

    channel = interaction.channel
    if not channel:
        await interaction.followup.send("无法在非频道环境中使用此命令。")
        return

    try:
        # 1. Fetch RMP reviews (last 50 to be safe)
        reviews = rmp_helper.get_reviews(count=50)

        # 2. Filter for last 5 days
        recent_reviews = []
        now = datetime.now(timezone.utc)

        for r in reviews:
            # Parse date: "2025-12-25 23:17:27 +0000 UTC"
            # We need to handle the format carefully.
            try:
                # Remove " UTC" at the end and parse
                date_str = r['date'].replace(" UTC", "")
                r_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")

                # Check if within 5 days
                if (now - r_date).days <= 5:
                    recent_reviews.append(r)
            except ValueError:
                # Fallback if format changes, maybe just skip date check or log error
                logger.warning(f"Failed to parse date: {r['date']}")
                continue

        if not recent_reviews:
            await interaction.followup.send("最近5天没有新的评价。")
            log_message("No recent reviews found (mynewsanrr)", channel.name, interaction.user.name)
            return

        # 3. Check channel history for these reviews
        # We look for the Review ID in the footer of embeds
        sent_ids = set()
        async for msg in channel.history(limit=200): # Check last 200 messages
            if msg.author == bot.user and msg.embeds:
                for embed in msg.embeds:
                    if embed.footer and embed.footer.text and "Review ID: " in embed.footer.text:
                        rid = embed.footer.text.replace("Review ID: ", "")
                        sent_ids.add(rid)

        # 4. Post missing reviews
        posted_count = 0
        details = rmp_helper.get_professor_details()
        prof_name = f"{details['firstName']} {details['lastName']}" if details else "Unknown Professor"

        # Reverse to post oldest first
        recent_reviews.reverse()

        for r in recent_reviews:
            if r['id'] not in sent_ids:
                await post_review(channel, r, prof_name, requester=interaction.user.name)
                posted_count += 1
                await asyncio.sleep(1)

        result_msg = f"检查完成。补发了 {posted_count} 条评价。"
        await interaction.followup.send(result_msg)
        log_message(result_msg, channel.name, interaction.user.name)

    except Exception as e:
        err_msg = f"执行出错: {str(e)}"
        await interaction.followup.send(err_msg)
        logger.error(err_msg)

@bot.tree.command(name="botlog", description="查看 Bot 最近发送的消息记录")
async def bot_log(interaction: discord.Interaction):
    if not os.path.exists(LOG_FILE):
        await interaction.response.send_message("暂无日志记录。")
        return

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            logs = json.load(f)

        if not logs:
            await interaction.response.send_message("暂无日志记录。")
            return

        # Get last 100
        recent_logs = logs[-100:]

        # Format output
        output = "### 最近 100 条消息记录:\n"
        for entry in recent_logs:
            line = f"[{entry['timestamp']}] **{entry['requester']}** @ {entry['channel']}: {entry['content'][:50]}...\n"
            if len(output) + len(line) > 1900: # Discord limit
                break
            output += line

        await interaction.response.send_message(output)

    except Exception as e:
        await interaction.response.send_message(f"读取日志出错: {str(e)}")


# --- 4. 同步指令 (管理员专用) ---
@bot.command()
async def sync(ctx):
    print("正在同步指令...")
    fmt = await ctx.bot.tree.sync()
    await ctx.send(f"同步完成！共同步了 {len(fmt)} 个指令。")
    log_message(f"Synced {len(fmt)} commands", ctx.channel.name, ctx.author.name)

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("错误：未在 .env 文件中找到 Token。")
