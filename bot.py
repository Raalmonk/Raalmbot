import discord
from discord import app_commands
from discord.ext import commands, tasks
import random
import json
import os
import asyncio
from dotenv import load_dotenv
from rmp_helper import RMPHelper
from datetime import datetime

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

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"rmp_channel_id": None, "seen_reviews": []}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2)

def create_review_embed(review, professor_details, title_prefix=""):
    """Creates a detailed embed for a review."""

    # Extract fields with safe fallbacks
    quality = review.get("helpfulRating", "N/A")
    difficulty = review.get("difficultyRating", "N/A")
    class_name = review.get("class", "N/A")
    date_str = review.get("date", "")

    # Parse date if possible (Format: 2025-12-23 02:05:15 +0000 UTC)
    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S +0000 UTC")
        formatted_date = date_obj.strftime("%Y-%m-%d")
    except ValueError:
        formatted_date = date_str

    for_credit = review.get("isForCredit")
    attendance = review.get("attendanceMandatory") # "mandatory", "non mandatory", or None
    grade = review.get("grade", "N/A")
    textbook = review.get("textbookUse") # Usually int or None
    tags = review.get("ratingTags", "")
    comment = review.get("comment", "No comment.")

    # Format values
    for_credit_str = "Yes" if for_credit is True else "No" if for_credit is False else "N/A"

    if attendance == "mandatory":
        attendance_str = "Mandatory"
    elif attendance == "non mandatory":
        attendance_str = "Not Mandatory"
    else:
        attendance_str = "N/A"

    # Textbook: RMP often returns integers for this or legacy values.
    # If -1 or similar, maybe treat as N/A or No?
    # Based on observation: 3 might be "Yes", -1 "No/Unknown".
    # Let's just show the raw value or map if we are sure.
    # User asked: Textbook Used (Yes/No).
    # If 1 or higher -> Yes? If 0 or -1 -> No?
    # Let's map somewhat safely.
    textbook_str = "N/A"
    if isinstance(textbook, int):
        if textbook > 0:
            textbook_str = "Yes"
        elif textbook <= 0:
            textbook_str = "No"

    # Tags formatting
    tags_str = tags if tags else "None"

    # Embed Construction
    embed = discord.Embed(
        title=f"{title_prefix}Review for {professor_details['firstName']} {professor_details['lastName']}",
        description=f"**Class:** {class_name}",
        color=discord.Color.blue()
    )

    embed.add_field(name="Quality", value=f"{quality}/5.0", inline=True)
    embed.add_field(name="Difficulty", value=f"{difficulty}/5.0", inline=True)
    embed.add_field(name="Date", value=formatted_date, inline=True)

    embed.add_field(name="For Credit", value=for_credit_str, inline=True)
    embed.add_field(name="Attendance", value=attendance_str, inline=True)
    embed.add_field(name="Grade Received", value=grade, inline=True)

    embed.add_field(name="Textbook Used", value=textbook_str, inline=True)
    embed.add_field(name="Tags", value=tags_str, inline=False)

    embed.add_field(name="Comment", value=comment, inline=False)

    embed.set_footer(text=f"Professor ID: {PROFESSOR_ID} | UMass Lowell")

    return embed

# --- Background Task ---

@tasks.loop(hours=1)
async def check_rmp_updates():
    config = load_config()
    channel_id = config.get("rmp_channel_id")

    if not channel_id:
        print("RMP Loop: No channel ID set. Use /set_rmp_channel to set it.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        print(f"RMP Loop: Channel {channel_id} not found.")
        return

    print("Checking for new RMP reviews...")
    try:
        # Fetch reviews (getting a few more to be safe)
        fetched_reviews = rmp_helper.get_reviews(count=20)
        if not fetched_reviews:
            print("No reviews found or error fetching.")
            return

        professor_details = rmp_helper.get_professor_details()
        if not professor_details:
             print("Could not fetch professor details for embed.")
             return

        seen_ids = set(config.get("seen_reviews", []))
        new_reviews = []

        # Determine if this is a "Backfill" (First run / no cache)
        is_backfill = len(seen_ids) == 0

        # Sort fetched reviews by date (newest first usually, but let's process carefully)
        # We want to post oldest to newest if we are backfilling, or just new ones.
        # But RMP returns newest first.

        # Identify new reviews
        reviews_to_post = []
        for review in fetched_reviews:
            rid = review["id"]
            if rid not in seen_ids:
                reviews_to_post.append(review)

        if not reviews_to_post:
            print("No new reviews.")
            return

        # If backfill, user requested "last 5-10 reviews".
        if is_backfill:
            print("First run detected. Backfilling history...")

            # Mark ALL fetched reviews as seen to prevent re-posting history later
            for review in fetched_reviews:
                 if review["id"] not in config["seen_reviews"]:
                     config["seen_reviews"].append(review["id"])

            # But only post the latest 5
            reviews_to_post = fetched_reviews[:5]
            reviews_to_post.reverse()

        else:
            # Not backfill, just new updates.
            # RMP returns [Newest, ..., Oldest].
            # If we have new reviews [New1, New2], we should post New2 then New1
            # so New1 is the latest message? Or just post them.
            # Usually chronological post order is better.
            reviews_to_post.reverse()

            # Update seen IDs for the new reviews we are about to post
            for review in reviews_to_post:
                config["seen_reviews"].append(review["id"])

        for review in reviews_to_post:
            embed = create_review_embed(review, professor_details, title_prefix="[New Review] " if not is_backfill else "[History] ")
            await channel.send(embed=embed)
            # Small delay to ensure order
            await asyncio.sleep(1)

        # Save config
        save_config(config)
        print(f"Posted {len(reviews_to_post)} reviews.")

    except Exception as e:
        print(f"Error in RMP loop: {e}")

@check_rmp_updates.before_loop
async def before_check_rmp_updates():
    await bot.wait_until_ready()

# --- Events & Commands ---

@bot.event
async def on_ready():
    print(f'RaalmBot 已上线: {bot.user} (ID: {bot.user.id})')

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

@bot.tree.command(name="rmsanrr", description="Show Professor Liu's Stats and Latest Review")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def rmsanrr(interaction: discord.Interaction):
    await interaction.response.defer()

    try:
        prof = rmp_helper.get_professor_details()
        reviews = rmp_helper.get_reviews(count=1)

        if not prof:
            await interaction.followup.send("Error: Could not fetch professor details.")
            return

        # Create Summary Embed
        summary_embed = discord.Embed(
            title=f"Professor {prof['firstName']} {prof['lastName']}",
            description=f"**Department:** {prof['department']}\n**School:** {prof['school']['name']}",
            color=discord.Color.green()
        )
        summary_embed.add_field(name="Avg Quality", value=f"{prof['avgRating']}/5.0", inline=True)
        summary_embed.add_field(name="Avg Difficulty", value=f"{prof['avgDifficulty']}/5.0", inline=True)
        summary_embed.add_field(name="Total Ratings", value=f"{prof['numRatings']}", inline=True)

        take_again = prof['wouldTakeAgainPercent']
        take_again_str = f"{take_again}%" if take_again is not None and take_again >= 0 else "N/A"
        summary_embed.add_field(name="Would Take Again", value=take_again_str, inline=True)

        summary_embed.set_thumbnail(url="https://www.ratemyprofessors.com/static/media/no-portrait.00000000.svg") # Generic placeholder

        embeds = [summary_embed]

        if reviews:
            latest_review = reviews[0]
            review_embed = create_review_embed(latest_review, prof, title_prefix="[Latest] ")
            embeds.append(review_embed)

        await interaction.followup.send(embeds=embeds)

    except Exception as e:
        await interaction.followup.send(f"An error occurred: {e}")

@bot.command()
@commands.has_permissions(administrator=True)
async def set_rmp_channel(ctx):
    """Sets the current channel for RMP auto-updates."""
    config = load_config()
    config["rmp_channel_id"] = ctx.channel.id
    save_config(config)
    await ctx.send(f"RateMyProfessor updates will now be posted to {ctx.channel.mention}")

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