import discord
from discord import app_commands
from discord.ext import commands
import random
import json
import os
from dotenv import load_dotenv

# 1. 加载 .env 文件里的 Token (安全措施)
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 2. 设置权限
intents = discord.Intents.default()
intents.message_content = True 

bot = commands.Bot(command_prefix="!", intents=intents)

# --- 辅助函数：读取回复列表 ---
def load_responses():
    # 每次调用时重新读取文件，这样你修改 json 后不用重启机器人也能生效
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

@tasks.loop(minutes=10)
async def check_rmp_updates():
    config = load_config()
    channel_id = config.get("rmp_channel_id")

    if not channel_id:
        print("RMP Loop: No channel ID set. Use /rmsanrr to start auto-fetch.")
        return

    channel = bot.get_channel(channel_id)
    if not channel:
        print(f"RMP Loop: Channel {channel_id} not found.")
        return

    print("Checking for new RMP reviews...")
    try:
        professor_details = rmp_helper.get_professor_details()
        if not professor_details:
             print("Could not fetch professor details for embed.")
             return

        # Dynamic count based on total ratings + buffer
        total_ratings = professor_details.get("numRatings", 20)
        count_to_fetch = total_ratings + 5

        fetched_reviews = rmp_helper.get_reviews(count=count_to_fetch)
        if not fetched_reviews:
            print("No reviews found or error fetching.")
            return

        seen_ids = set(config.get("seen_reviews", []))

        # Determine if this is a "Backfill" (First run / no cache)
        is_backfill = len(seen_ids) == 0

        reviews_to_post = []

        # Filter new reviews
        if is_backfill:
            # If backfill, user wants ALL history.
            print("First run detected. Backfilling FULL history...")
            reviews_to_post = fetched_reviews
            # Reverse to post Oldest -> Newest
            reviews_to_post.reverse()

            # Mark all as seen
            for review in fetched_reviews:
                 if review["id"] not in config["seen_reviews"]:
                     config["seen_reviews"].append(review["id"])
        else:
            # Identify new reviews only
            for review in fetched_reviews:
                rid = review["id"]
                if rid not in seen_ids:
                    reviews_to_post.append(review)

            if not reviews_to_post:
                print("No new reviews.")
                return

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
    # 注意：这里我们依靠下面的 !sync 指令来同步，防止自动同步被限流

# --- 3. 创建 /wsnd 指令 ---
@bot.tree.command(name="wsnd", description="随机抽取一条回复")
# 允许在服务器和私聊中使用
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def wsnd(interaction: discord.Interaction):
    # 读取数据
    options = load_responses()
    # 随机选择
    selected = random.choice(options)
    # 发送
    await interaction.response.send_message(selected)

# --- 3.1 创建 /抽一签 指令 ---
@bot.tree.command(name="抽一签", description="想你了m萨")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def draw_lot(interaction: discord.Interaction):
    fortunes = load_fortunes()
    selected = random.choice(fortunes)
    await interaction.response.send_message(selected)

# --- RMP Commands ---

@bot.tree.command(name="rmsanrr", description="Start auto-fetching reviews for Professor Liu (Backfills History)")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def rmsanrr(interaction: discord.Interaction):
    # This command now starts the process
    # 1. Sets the channel
    # 2. Clears seen_reviews (to force backfill)
    # 3. Restarts the background loop

    await interaction.response.defer()

    config = load_config()
    config["rmp_channel_id"] = interaction.channel_id
    config["seen_reviews"] = [] # Force backfill
    save_config(config)

    await interaction.followup.send("Starting auto-fetch for Pengyuan Liu... (Fetching history now)")

    # Restart the loop to trigger immediately
    if check_rmp_updates.is_running():
        check_rmp_updates.restart()
    else:
        check_rmp_updates.start()

@bot.tree.command(name="byebyesanrr", description="Stop auto-fetching reviews for Professor Liu")
@app_commands.allowed_installs(guilds=True, users=True)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def byebyesanrr(interaction: discord.Interaction):
    await interaction.response.defer()

    config = load_config()
    config["rmp_channel_id"] = None
    save_config(config)

    await interaction.followup.send("Stopped auto-fetch for Pengyuan Liu.")
    # We don't necessarily need to stop the loop object, just set config to None (it handles it).
    # But we can cancel it if we want to save resources.
    # Let's keep it running but idling as per loop logic.

@bot.command()
@commands.has_permissions(administrator=True)
async def force_rmp_check(ctx):
    """Manually triggers the RateMyProfessor update check."""
    await ctx.send("Manually triggering RMP update check...")
    # We call the loop function manually.
    # Note: Calling the task function directly works as a coroutine.
    await check_rmp_updates()

@bot.command()
async def sync(ctx):
    # 将下面的 ID 换成你自己的 Discord 用户 ID，防止别人乱同步
    # if ctx.author.id != 你的用户ID: return 
    
    print("正在同步指令...")
    fmt = await ctx.bot.tree.sync()
    await ctx.send(f"同步完成！共同步了 {len(fmt)} 个指令。")

if __name__ == "__main__":
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("错误：未在 .env 文件中找到 Token。")