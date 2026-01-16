import os
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import json

# ============ CONFIGURATION ============
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
SOLANA_RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Store tracked wallets in memory
user_data = {}

# ============ SOLANA BLOCKCHAIN FUNCTIONS ============

async def get_wallet_balance(address: str) -> dict:
    """Get SOL balance and basic info for a wallet"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBalance",
            "params": [address]
        }
        
        try:
            async with session.post(SOLANA_RPC_URL, json=payload) as response:
                data = await response.json()
                if 'result' in data:
                    sol_balance = data['result']['value'] / 1_000_000_000
                    return {'success': True, 'balance': sol_balance}
                else:
                    return {'success': False, 'error': 'Invalid response'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

async def get_recent_transactions(address: str, limit: int = 5) -> dict:
    """Get recent transactions for a wallet"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [address, {"limit": limit}]
        }
        
        try:
            async with session.post(SOLANA_RPC_URL, json=payload) as response:
                data = await response.json()
                if 'result' in data:
                    return {'success': True, 'transactions': data['result']}
                else:
                    return {'success': False, 'error': 'Invalid response'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

# ============ BOT COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message when user starts the bot"""
    welcome_message = (
        "🤖 *Welcome to Solana Wallet Tracker Bot!*\n\n"
        "I can help you track Solana wallet addresses and notify you of new transactions.\n\n"
        "*Available Commands:*\n"
        "/add `<wallet_address>` - Add a wallet to track\n"
        "/remove `<wallet_address>` - Stop tracking a wallet\n"
        "/list - Show all wallets you're tracking\n"
        "/balance `<wallet_address>` - Check wallet balance\n"
        "/recent `<wallet_address>` - Show recent transactions\n"
        "/help - Show this message\n\n"
        "💡 *Tip:* Once you add a wallet, I'll automatically notify you of new transactions!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await start(update, context)

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a wallet address to track"""
    user_id = update.effective_user.id
    
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/add <wallet_address>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    if len(wallet_address) < 32 or len(wallet_address) > 44:
        await update.message.reply_text("❌ Invalid Solana wallet address format.")
        return
    
    if user_id not in user_data:
        user_data[user_id] = {'wallets': [], 'last_signatures': {}}
    
    if wallet_address in user_data[user_id]['wallets']:
        await update.message.reply_text("⚠️ You're already tracking this wallet!")
        return
    
    balance_result = await get_wallet_balance(wallet_address)
    if not balance_result['success']:
        await update.message.reply_text(
            f"❌ Could not verify wallet address.\n"
            f"Error: {balance_result.get('error', 'Unknown error')}"
        )
        return
    
    user_data[user_id]['wallets'].append(wallet_address)
    
    tx_result = await get_recent_transactions(wallet_address, 1)
    if tx_result['success'] and tx_result['transactions']:
        user_data[user_id]['last_signatures'][wallet_address] = tx_result['transactions'][0]['signature']
    
    await update.message.reply_text(
        f"✅ Now tracking wallet:\n`{wallet_address}`\n\n"
        f"💰 Current balance: {balance_result['balance']:.4f} SOL\n\n"
        "I'll notify you of new transactions!",
        parse_mode='Markdown'
    )

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a wallet from tracking"""
    user_id = update.effective_user.id
    
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/remove <wallet_address>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    if user_id not in user_data or wallet_address not in user_data[user_id]['wallets']:
        await update.message.reply_text("❌ You're not tracking this wallet.")
        return
    
    user_data[user_id]['wallets'].remove(wallet_address)
    if wallet_address in user_data[user_id]['last_signatures']:
        del user_data[user_id]['last_signatures'][wallet_address]
    
    await update.message.reply_text(
        f"✅ Stopped tracking:\n`{wallet_address}`",
        parse_mode='Markdown'
    )

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all tracked wallets"""
    user_id = update.effective_user.id
    
    if user_id not in user_data or not user_data[user_id]['wallets']:
        await update.message.reply_text(
            "📭 You're not tracking any wallets yet.\n\n"
            "Use `/add <wallet_address>` to start tracking!",
            parse_mode='Markdown'
        )
        return
    
    wallets = user_data[user_id]['wallets']
    message = f"📊 *Your Tracked Wallets ({len(wallets)}):*\n\n"
    
    for i, wallet in enumerate(wallets, 1):
        message += f"{i}. `{wallet}`\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check balance of a wallet"""
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/balance <wallet_address>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    await update.message.reply_text("⏳ Fetching balance...")
    
    balance_result = await get_wallet_balance(wallet_address)
    
    if not balance_result['success']:
        await update.message.reply_text(
            f"❌ Could not fetch balance.\n"
            f"Error: {balance_result.get('error', 'Unknown error')}"
        )
        return
    
    await update.message.reply_text(
        f"💰 *Wallet Balance*\n\n"
        f"Address: `{wallet_address}`\n"
        f"Balance: *{balance_result['balance']:.4f} SOL*",
        parse_mode='Markdown'
    )

async def show_recent_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent transactions for a wallet"""
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/recent <wallet_address>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    await update.message.reply_text("⏳ Fetching transactions...")
    
    tx_result = await get_recent_transactions(wallet_address, 5)
    
    if not tx_result['success']:
        await update.message.reply_text(
            f"❌ Could not fetch transactions.\n"
            f"Error: {tx_result.get('error', 'Unknown error')}"
        )
        return
    
    transactions = tx_result['transactions']
    
    if not transactions:
        await update.message.reply_text("📭 No recent transactions found.")
        return
    
    message = f"📜 *Recent Transactions*\n\n"
    
    for i, tx in enumerate(transactions[:5], 1):
        signature = tx['signature']
        short_sig = f"{signature[:8]}...{signature[-8:]}"
        timestamp = datetime.fromtimestamp(tx['blockTime']).strftime('%Y-%m-%d %H:%M:%S')
        status = "✅" if tx.get('err') is None else "❌"
        
        message += f"{i}. {status} `{short_sig}`\n"
        message += f"   ⏰ {timestamp}\n"
        message += f"   🔗 [View on Solscan](https://solscan.io/tx/{signature})\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

# ============ BACKGROUND MONITORING ============

async def monitor_wallets(application: Application):
    """Background task to monitor all tracked wallets for new transactions"""
    print("🔍 Wallet monitoring started...")
    
    while True:
        try:
            for user_id, data in list(user_data.items()):
                for wallet_address in data['wallets']:
                    tx_result = await get_recent_transactions(wallet_address, 1)
                    
                    if not tx_result['success'] or not tx_result['transactions']:
                        continue
                    
                    latest_tx = tx_result['transactions'][0]
                    latest_signature = latest_tx['signature']
                    
                    last_known_signature = data['last_signatures'].get(wallet_address)
                    
                    if last_known_signature and latest_signature != last_known_signature:
                        data['last_signatures'][wallet_address] = latest_signature
                        
                        timestamp = datetime.fromtimestamp(latest_tx['blockTime']).strftime('%Y-%m-%d %H:%M:%S')
                        status = "✅ Success" if latest_tx.get('err') is None else "❌ Failed"
                        
                        notification = (
                            f"🔔 *New Transaction Detected!*\n\n"
                            f"Wallet: `{wallet_address}`\n"
                            f"Status: {status}\n"
                            f"Time: {timestamp}\n"
                            f"Signature: `{latest_signature[:16]}...`\n\n"
                            f"🔗 [View on Solscan](https://solscan.io/tx/{latest_signature})"
                        )
                        
                        try:
                            await application.bot.send_message(
                                chat_id=user_id,
                                text=notification,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            print(f"Error sending notification to user {user_id}: {e}")
                    
                    elif not last_known_signature:
                        data['last_signatures'][wallet_address] = latest_signature
            
            await asyncio.sleep(15)
            
        except Exception as e:
            print(f"Error in monitoring loop: {e}")
            await asyncio.sleep(30)

# ============ MAIN FUNCTION ============

def main():
    """Start the bot"""
    
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("❌ ERROR: Please set your TELEGRAM_BOT_TOKEN!")
        print("Get your token from @BotFather on Telegram")
        return
    
    # Create the Application (without job_queue to avoid Python 3.13 issues)
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("recent", show_recent_transactions))
    
    # Start the monitoring task in the background
    async def post_init(app: Application):
        asyncio.create_task(monitor_wallets(app))
    
    application.post_init = post_init
    
    # Start the bot
    print("🤖 Bot is starting...")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
