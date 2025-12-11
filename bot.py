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

# --- 4. 同步指令 (管理员专用) ---
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