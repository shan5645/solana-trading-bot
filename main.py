import os
import asyncio
import aiohttp
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
import json
from typing import Optional, Dict, List

# ============ CONFIGURATION ============
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
SOLANA_RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Token program IDs
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
ASSOCIATED_TOKEN_PROGRAM_ID = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

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

async def get_transaction_details(signature: str) -> dict:
    """Get detailed transaction information including token transfers"""
    async with aiohttp.ClientSession() as session:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0
                }
            ]
        }
        
        try:
            async with session.post(SOLANA_RPC_URL, json=payload) as response:
                data = await response.json()
                if 'result' in data and data['result']:
                    return {'success': True, 'transaction': data['result']}
                else:
                    return {'success': False, 'error': 'Transaction not found'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

async def get_token_metadata(mint_address: str) -> dict:
    """Get token metadata (name, symbol, decimals)"""
    async with aiohttp.ClientSession() as session:
        # Try to get token metadata from Jupiter API
        try:
            async with session.get(f"https://tokens.jup.ag/token/{mint_address}") as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        'success': True,
                        'symbol': data.get('symbol', 'UNKNOWN'),
                        'name': data.get('name', 'Unknown Token'),
                        'decimals': data.get('decimals', 9)
                    }
        except:
            pass
        
        # Fallback: get decimals from Solana RPC
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                mint_address,
                {"encoding": "jsonParsed"}
            ]
        }
        
        try:
            async with session.post(SOLANA_RPC_URL, json=payload) as response:
                data = await response.json()
                if 'result' in data and data['result'] and data['result']['value']:
                    parsed = data['result']['value']['data']['parsed']
                    decimals = parsed['info']['decimals']
                    return {
                        'success': True,
                        'symbol': f"{mint_address[:4]}...{mint_address[-4:]}",
                        'name': 'Unknown Token',
                        'decimals': decimals
                    }
        except:
            pass
        
        return {
            'success': False,
            'symbol': 'UNKNOWN',
            'name': 'Unknown Token',
            'decimals': 9
        }

def parse_token_transfers(tx_data: dict, wallet_address: str) -> List[Dict]:
    """Parse transaction to find token transfers (buys/sells)"""
    transfers = []
    
    try:
        if not tx_data.get('meta'):
            return transfers
        
        pre_balances = tx_data['meta'].get('preTokenBalances', [])
        post_balances = tx_data['meta'].get('postTokenBalances', [])
        
        # Create maps for easier lookup
        pre_map = {}
        post_map = {}
        
        for balance in pre_balances:
            owner = balance.get('owner')
            mint = balance.get('mint')
            amount = float(balance.get('uiTokenAmount', {}).get('uiAmount', 0))
            if owner and mint:
                key = f"{owner}_{mint}"
                pre_map[key] = {
                    'amount': amount,
                    'mint': mint,
                    'decimals': balance.get('uiTokenAmount', {}).get('decimals', 9)
                }
        
        for balance in post_balances:
            owner = balance.get('owner')
            mint = balance.get('mint')
            amount = float(balance.get('uiTokenAmount', {}).get('uiAmount', 0))
            if owner and mint:
                key = f"{owner}_{mint}"
                post_map[key] = {
                    'amount': amount,
                    'mint': mint,
                    'decimals': balance.get('uiTokenAmount', {}).get('decimals', 9)
                }
        
        # Find changes for our wallet
        all_keys = set(pre_map.keys()) | set(post_map.keys())
        
        for key in all_keys:
            if not key.startswith(wallet_address):
                continue
            
            pre_amount = pre_map.get(key, {}).get('amount', 0)
            post_amount = post_map.get(key, {}).get('amount', 0)
            
            if pre_amount == post_amount:
                continue
            
            change = post_amount - pre_amount
            mint = post_map.get(key, pre_map.get(key, {})).get('mint')
            
            if mint and change != 0:
                transfers.append({
                    'mint': mint,
                    'change': change,
                    'type': 'BUY' if change > 0 else 'SELL',
                    'amount': abs(change)
                })
        
        # Also check SOL balance changes
        pre_sol = tx_data['meta'].get('preBalances', [])
        post_sol = tx_data['meta'].get('postBalances', [])
        account_keys = tx_data['transaction']['message']['accountKeys']
        
        for i, key in enumerate(account_keys):
            addr = key if isinstance(key, str) else key.get('pubkey')
            if addr == wallet_address:
                if i < len(pre_sol) and i < len(post_sol):
                    pre_balance = pre_sol[i] / 1_000_000_000
                    post_balance = post_sol[i] / 1_000_000_000
                    sol_change = post_balance - pre_balance
                    
                    if abs(sol_change) > 0.001:  # Ignore dust and fees
                        transfers.append({
                            'mint': 'SOL',
                            'change': sol_change,
                            'type': 'RECEIVE' if sol_change > 0 else 'SEND',
                            'amount': abs(sol_change),
                            'symbol': 'SOL',
                            'is_sol': True
                        })
                break
        
    except Exception as e:
        print(f"Error parsing token transfers: {e}")
    
    return transfers

# ============ BOT COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message when user starts the bot"""
    welcome_message = (
        "🤖 *Welcome to Solana Wallet Tracker Bot!*\n\n"
        "I can help you track Solana wallet addresses and notify you of new transactions with token buy/sell details.\n\n"
        "*Available Commands:*\n"
        "/add `<wallet_address>` `[name]` - Add a wallet to track\n"
        "/rename `<wallet_address>` `<new_name>` - Rename a tracked wallet\n"
        "/remove `<wallet_address>` - Stop tracking a wallet\n"
        "/list - Show all tracked wallets\n"
        "/balance `<wallet_address>` - Check wallet balance\n"
        "/recent `<wallet_address>` - Show recent transactions with token details\n"
        "/stats - Show tracking statistics\n"
        "/help - Show this message\n\n"
        "💡 *Features:*\n"
        "• Real-time transaction notifications\n"
        "• Token buy/sell detection\n"
        "• Transaction amounts and token symbols\n"
        "• 15-second monitoring interval\n\n"
        "📊 Once you add a wallet, I'll automatically notify you of new transactions with full details!"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await start(update, context)

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a wallet address to track with optional name"""
    user_id = update.effective_user.id
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/add <wallet_address> [name]`\n\n"
            "Examples:\n"
            "`/add DYw8jCTfwHUet3BebGCGJk...xyz MyWallet`\n"
            "`/add DYw8jCTfwHUet3BebGCGJk...xyz`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    wallet_name = ' '.join(context.args[1:]).strip() if len(context.args) > 1 else None
    
    if len(wallet_address) < 32 or len(wallet_address) > 44:
        await update.message.reply_text("❌ Invalid Solana wallet address format.")
        return
    
    if user_id not in user_data:
        user_data[user_id] = {'wallets': {}, 'last_signatures': {}}
    
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
    
    if not wallet_name:
        wallet_name = f"{wallet_address[:4]}...{wallet_address[-4:]}"
    
    user_data[user_id]['wallets'][wallet_address] = wallet_name
    
    tx_result = await get_recent_transactions(wallet_address, 1)
    if tx_result['success'] and tx_result['transactions']:
        user_data[user_id]['last_signatures'][wallet_address] = tx_result['transactions'][0]['signature']
    
    await update.message.reply_text(
        f"✅ Now tracking wallet:\n"
        f"📛 Name: *{wallet_name}*\n"
        f"📍 Address: `{wallet_address}`\n"
        f"💰 Current balance: *{balance_result['balance']:.4f} SOL*\n\n"
        "I'll notify you of new transactions with token buy/sell details!",
        parse_mode='Markdown'
    )

async def rename_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rename a tracked wallet"""
    user_id = update.effective_user.id
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Please provide a wallet address and new name.\n"
            "Usage: `/rename <wallet_address> <new_name>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    new_name = ' '.join(context.args[1:]).strip()
    
    if user_id not in user_data or wallet_address not in user_data[user_id]['wallets']:
        await update.message.reply_text("❌ You're not tracking this wallet. Use /list to see your tracked wallets.")
        return
    
    old_name = user_data[user_id]['wallets'][wallet_address]
    user_data[user_id]['wallets'][wallet_address] = new_name
    
    await update.message.reply_text(
        f"✅ Wallet renamed!\n"
        f"Old name: *{old_name}*\n"
        f"New name: *{new_name}*\n"
        f"Address: `{wallet_address}`",
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
    
    wallet_name = user_data[user_id]['wallets'][wallet_address]
    del user_data[user_id]['wallets'][wallet_address]
    
    if wallet_address in user_data[user_id]['last_signatures']:
        del user_data[user_id]['last_signatures'][wallet_address]
    
    await update.message.reply_text(
        f"✅ Stopped tracking:\n"
        f"📛 Name: *{wallet_name}*\n"
        f"📍 Address: `{wallet_address}`",
        parse_mode='Markdown'
    )

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all tracked wallets with their names"""
    user_id = update.effective_user.id
    
    if user_id not in user_data or not user_data[user_id]['wallets']:
        await update.message.reply_text(
            "📭 You're not tracking any wallets yet.\n\n"
            "Use `/add <wallet_address> [name]` to start tracking!",
            parse_mode='Markdown'
        )
        return
    
    wallets = user_data[user_id]['wallets']
    message = f"📊 *Your Tracked Wallets ({len(wallets)}):*\n\n"
    
    for i, (address, name) in enumerate(wallets.items(), 1):
        short_address = f"{address[:6]}...{address[-6:]}"
        message += f"{i}. 📛 *{name}*\n"
        message += f"   📍 `{short_address}`\n"
        message += f"   🔗 [View on Solscan](https://solscan.io/account/{address})\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user statistics"""
    user_id = update.effective_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("📊 You haven't started tracking any wallets yet!")
        return
    
    wallet_count = len(user_data[user_id]['wallets'])
    named_count = sum(1 for name in user_data[user_id]['wallets'].values() 
                      if not (name.startswith('...') or '...' in name[:10]))
    
    message = (
        f"📊 *Your Statistics*\n\n"
        f"👛 Total wallets tracked: *{wallet_count}*\n"
        f"📛 Named wallets: *{named_count}*\n"
        f"🏷️ Auto-named wallets: *{wallet_count - named_count}*\n"
        f"⏱️ Monitoring interval: *15 seconds*\n"
        f"💡 Recommended max: *50 wallets*"
    )
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check balance of a wallet"""
    user_id = update.effective_user.id
    
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/balance <wallet_address>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    wallet_name = None
    if user_id in user_data and wallet_address in user_data[user_id]['wallets']:
        wallet_name = user_data[user_id]['wallets'][wallet_address]
    
    await update.message.reply_text("⏳ Fetching balance...")
    
    balance_result = await get_wallet_balance(wallet_address)
    
    if not balance_result['success']:
        await update.message.reply_text(
            f"❌ Could not fetch balance.\n"
            f"Error: {balance_result.get('error', 'Unknown error')}"
        )
        return
    
    message = f"💰 *Wallet Balance*\n\n"
    if wallet_name:
        message += f"📛 Name: *{wallet_name}*\n"
    message += f"📍 Address: `{wallet_address}`\n"
    message += f"💵 Balance: *{balance_result['balance']:.4f} SOL*"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def show_recent_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent transactions with token buy/sell details"""
    user_id = update.effective_user.id
    
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ Please provide a wallet address.\n"
            "Usage: `/recent <wallet_address>`",
            parse_mode='Markdown'
        )
        return
    
    wallet_address = context.args[0].strip()
    
    wallet_name = None
    if user_id in user_data and wallet_address in user_data[user_id]['wallets']:
        wallet_name = user_data[user_id]['wallets'][wallet_address]
    
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
    if wallet_name:
        message += f"📛 Wallet: *{wallet_name}*\n\n"
    
    for i, tx in enumerate(transactions[:5], 1):
        signature = tx['signature']
        short_sig = f"{signature[:8]}...{signature[-8:]}"
        timestamp = datetime.fromtimestamp(tx['blockTime']).strftime('%Y-%m-%d %H:%M:%S')
        status = "✅" if tx.get('err') is None else "❌"
        
        message += f"{i}. {status} `{short_sig}`\n"
        message += f"   ⏰ {timestamp}\n"
        
        # Fetch detailed transaction info
        tx_details = await get_transaction_details(signature)
        if tx_details['success']:
            transfers = parse_token_transfers(tx_details['transaction'], wallet_address)
            
            if transfers:
                for transfer in transfers:
                    if transfer.get('is_sol'):
                        emoji = "📥" if transfer['type'] == 'RECEIVE' else "📤"
                        message += f"   {emoji} {transfer['type']}: *{transfer['amount']:.4f} SOL*\n"
                    else:
                        # Get token metadata
                        token_info = await get_token_metadata(transfer['mint'])
                        symbol = token_info['symbol'] if token_info['success'] else 'UNKNOWN'
                        emoji = "🟢" if transfer['type'] == 'BUY' else "🔴"
                        message += f"   {emoji} {transfer['type']}: *{transfer['amount']:.4f} {symbol}*\n"
        
        message += f"   🔗 [View on Solscan](https://solscan.io/tx/{signature})\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown', disable_web_page_preview=True)

# ============ BACKGROUND MONITORING ============

async def monitor_wallets(application: Application):
    """Background task to monitor all tracked wallets for new transactions"""
    print("🔍 Wallet monitoring started with token detection...")
    
    while True:
        try:
            for user_id, data in list(user_data.items()):
                for wallet_address, wallet_name in data['wallets'].items():
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
                            f"📛 Wallet: *{wallet_name}*\n"
                            f"📍 Address: `{wallet_address[:8]}...{wallet_address[-8:]}`\n"
                            f"Status: {status}\n"
                            f"Time: {timestamp}\n\n"
                        )
                        
                        # Get transaction details
                        tx_details = await get_transaction_details(latest_signature)
                        if tx_details['success']:
                            transfers = parse_token_transfers(tx_details['transaction'], wallet_address)
                            
                            if transfers:
                                notification += "*Transaction Details:*\n"
                                for transfer in transfers:
                                    if transfer.get('is_sol'):
                                        emoji = "📥" if transfer['type'] == 'RECEIVE' else "📤"
                                        notification += f"{emoji} {transfer['type']}: *{transfer['amount']:.4f} SOL*\n"
                                    else:
                                        token_info = await get_token_metadata(transfer['mint'])
                                        symbol = token_info['symbol'] if token_info['success'] else 'UNKNOWN'
                                        emoji = "🟢" if transfer['type'] == 'BUY' else "🔴"
                                        notification += f"{emoji} {transfer['type']}: *{transfer['amount']:.4f} {symbol}*\n"
                                notification += "\n"
                        
                        notification += f"🔗 [View on Solscan](https://solscan.io/tx/{latest_signature})"
                        
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
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("rename", rename_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("recent", show_recent_transactions))
    application.add_handler(CommandHandler("stats", stats_command))
    
    async def post_init(app: Application):
        commands = [
            BotCommand("start", "🏠 Start the bot"),
            BotCommand("add", "➕ Add wallet to track"),
            BotCommand("remove", "➖ Remove wallet"),
            BotCommand("list", "📋 Show tracked wallets"),
            BotCommand("rename", "✏️ Rename wallet"),
            BotCommand("balance", "💰 Check balance"),
            BotCommand("recent", "📜 Recent transactions with tokens"),
            BotCommand("stats", "📊 Your statistics"),
            BotCommand("help", "❓ Help message"),
        ]
        await app.bot.set_my_commands(commands)
        asyncio.create_task(monitor_wallets(app))
    
    application.post_init = post_init
    
    print("🤖 Bot starting with token buy/sell detection...")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
