import os
import asyncio
import aiohttp
import json
from datetime import datetime
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes
import logging

# ============ LOGGING SETUP ============
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============ CONFIGURATION ============
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN_HERE')
SOLANA_RPC_URL = os.environ.get('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# File to store user data persistently
DATA_FILE = 'wallet_data.json'

# Store tracked wallets in memory
user_data = {}

# Cache for token metadata
token_metadata_cache = {}

# ============ DATA PERSISTENCE ============

def save_data():
    """Save user data to file"""
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(user_data, f, indent=2)
        logger.info("💾 Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

def load_data():
    """Load user data from file"""
    global user_data
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                user_data = json.load(f)
            logger.info(f"📂 Loaded data for {len(user_data)} users")
            
            # Count total wallets
            total_wallets = sum(len(data.get('wallets', {})) for data in user_data.values())
            logger.info(f"📊 Total tracked wallets: {total_wallets}")
        else:
            logger.info("📂 No saved data found, starting fresh")
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        user_data = {}

# ============ SOLANA FUNCTIONS ============

async def get_wallet_balance(address: str) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]}
            async with session.post(SOLANA_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                data = await response.json()
                if 'result' in data:
                    return {'success': True, 'balance': data['result']['value'] / 1_000_000_000}
                return {'success': False, 'error': 'Invalid response'}
    except Exception as e:
        logger.error(f"Error getting balance: {e}")
        return {'success': False, 'error': str(e)}

async def get_recent_transactions(address: str, limit: int = 5) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            payload = {"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress", "params": [address, {"limit": limit}]}
            async with session.post(SOLANA_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                data = await response.json()
                if 'result' in data:
                    return {'success': True, 'transactions': data['result']}
                return {'success': False, 'error': 'Invalid response'}
    except Exception as e:
        logger.error(f"Error getting transactions: {e}")
        return {'success': False, 'error': str(e)}

async def get_transaction_details(signature: str) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            payload = {
                "jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]
            }
            async with session.post(SOLANA_RPC_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as response:
                data = await response.json()
                if 'result' in data and data['result']:
                    return {'success': True, 'transaction': data['result']}
                return {'success': False, 'error': 'Transaction not found'}
    except Exception as e:
        logger.error(f"Error getting tx details: {e}")
        return {'success': False, 'error': str(e)}

async def get_token_metadata(mint_address: str) -> dict:
    if mint_address in token_metadata_cache:
        return token_metadata_cache[mint_address]
    
    if mint_address == 'So11111111111111111111111111111111111111112':
        result = {'success': True, 'symbol': 'SOL', 'name': 'Solana', 'decimals': 9}
        token_metadata_cache[mint_address] = result
        return result
    
    try:
        async with aiohttp.ClientSession() as session:
            # Try Solscan
            try:
                headers = {'User-Agent': 'Mozilla/5.0'}
                async with session.get(f'https://pro-api.solscan.io/v1.0/token/meta?tokenAddress={mint_address}', 
                                      headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('symbol'):
                            result = {'success': True, 'symbol': data['symbol'], 'name': data.get('name', 'Unknown'), 'decimals': data.get('decimals', 9)}
                            token_metadata_cache[mint_address] = result
                            logger.info(f"Found via Solscan: {result['symbol']}")
                            return result
            except Exception as e:
                logger.debug(f"Solscan failed: {e}")
            
            # Try DexScreener
            try:
                async with session.get(f'https://api.dexscreener.com/latest/dex/tokens/{mint_address}',
                                      timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('pairs') and len(data['pairs']) > 0:
                            base_token = data['pairs'][0].get('baseToken', {})
                            if base_token.get('address') == mint_address:
                                result = {'success': True, 'symbol': base_token['symbol'], 'name': base_token.get('name', 'Unknown'), 'decimals': 9}
                                token_metadata_cache[mint_address] = result
                                logger.info(f"Found via DexScreener: {result['symbol']}")
                                return result
            except Exception as e:
                logger.debug(f"DexScreener failed: {e}")
            
            # Try Jupiter
            try:
                async with session.get('https://token.jup.ag/strict', timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        tokens = await response.json()
                        for token in tokens:
                            if token.get('address') == mint_address:
                                result = {'success': True, 'symbol': token['symbol'], 'name': token.get('name', 'Unknown'), 'decimals': token.get('decimals', 9)}
                                token_metadata_cache[mint_address] = result
                                logger.info(f"Found via Jupiter: {result['symbol']}")
                                return result
            except Exception as e:
                logger.debug(f"Jupiter failed: {e}")
    
    except Exception as e:
        logger.error(f"Error in get_token_metadata: {e}")
    
    result = {'success': False, 'symbol': f"{mint_address[:4]}...{mint_address[-4:]}", 'name': 'Unknown', 'decimals': 9}
    token_metadata_cache[mint_address] = result
    return result

def parse_token_transfers(tx_data: dict, wallet_address: str):
    transfers = []
    try:
        if not tx_data.get('meta'):
            return transfers
        
        pre_balances = tx_data['meta'].get('preTokenBalances', [])
        post_balances = tx_data['meta'].get('postTokenBalances', [])
        
        pre_map = {}
        post_map = {}
        
        for balance in pre_balances:
            owner = balance.get('owner')
            mint = balance.get('mint')
            amount = float(balance.get('uiTokenAmount', {}).get('uiAmount', 0) or 0)
            if owner and mint:
                pre_map[f"{owner}_{mint}"] = {'amount': amount, 'mint': mint}
        
        for balance in post_balances:
            owner = balance.get('owner')
            mint = balance.get('mint')
            amount = float(balance.get('uiTokenAmount', {}).get('uiAmount', 0) or 0)
            if owner and mint:
                post_map[f"{owner}_{mint}"] = {'amount': amount, 'mint': mint}
        
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
                transfers.append({'mint': mint, 'change': change, 'type': 'BUY' if change > 0 else 'SELL', 'amount': abs(change)})
        
        # Check SOL changes
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
                    
                    if abs(sol_change) > 0.001:
                        transfers.append({
                            'mint': 'SOL', 'change': sol_change,
                            'type': 'RECEIVE' if sol_change > 0 else 'SEND',
                            'amount': abs(sol_change), 'symbol': 'SOL', 'is_sol': True
                        })
                break
    
    except Exception as e:
        logger.error(f"Error parsing transfers: {e}")
    
    return transfers

# ============ BOT COMMANDS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = (
            "🤖 *Solana Wallet Tracker Bot*\n\n"
            "*Commands:*\n"
            "/add `<address>` `[name]` - Track a wallet\n"
            "/remove `<address>` - Stop tracking\n"
            "/list - Show tracked wallets\n"
            "/balance `<address>` - Check balance\n"
            "/recent `<address>` - Recent transactions\n"
            "/stats - Your statistics\n\n"
            "I'll notify you of new transactions with token details!"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
        logger.info(f"User {update.effective_user.id} started bot")
    except Exception as e:
        logger.error(f"Error in start: {e}")

async def add_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if len(context.args) < 1:
            await update.message.reply_text("❌ Usage: `/add <address> [name]`", parse_mode='Markdown')
            return
        
        wallet_address = context.args[0].strip()
        wallet_name = ' '.join(context.args[1:]).strip() if len(context.args) > 1 else f"{wallet_address[:4]}...{wallet_address[-4:]}"
        
        if len(wallet_address) < 32 or len(wallet_address) > 44:
            await update.message.reply_text("❌ Invalid address format")
            return
        
        if user_id not in user_data:
            user_data[user_id] = {'wallets': {}, 'last_signatures': {}}
        
        if wallet_address in user_data[user_id]['wallets']:
            await update.message.reply_text("⚠️ Already tracking this wallet!")
            return
        
        balance_result = await get_wallet_balance(wallet_address)
        if not balance_result['success']:
            await update.message.reply_text(f"❌ Could not verify wallet: {balance_result.get('error')}")
            return
        
        user_data[user_id]['wallets'][wallet_address] = wallet_name
        
        tx_result = await get_recent_transactions(wallet_address, 1)
        if tx_result['success'] and tx_result['transactions']:
            user_data[user_id]['last_signatures'][wallet_address] = tx_result['transactions'][0]['signature']
        
        save_data()  # Save after adding wallet
        
        await update.message.reply_text(
            f"✅ Now tracking:\n📛 *{wallet_name}*\n💰 Balance: *{balance_result['balance']:.4f} SOL*",
            parse_mode='Markdown'
        )
        logger.info(f"User {user_id} added {wallet_name}")
    except Exception as e:
        logger.error(f"Error in add_wallet: {e}")
        await update.message.reply_text("❌ Error occurred")

async def remove_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if len(context.args) != 1:
            await update.message.reply_text("❌ Usage: `/remove <address>`", parse_mode='Markdown')
            return
        
        wallet_address = context.args[0].strip()
        
        if user_id not in user_data or wallet_address not in user_data[user_id]['wallets']:
            await update.message.reply_text("❌ Not tracking this wallet")
            return
        
        wallet_name = user_data[user_id]['wallets'][wallet_address]
        del user_data[user_id]['wallets'][wallet_address]
        
        if wallet_address in user_data[user_id]['last_signatures']:
            del user_data[user_id]['last_signatures'][wallet_address]
        
        save_data()  # Save after removing wallet
        
        await update.message.reply_text(f"✅ Stopped tracking: *{wallet_name}*", parse_mode='Markdown')
        logger.info(f"User {user_id} removed {wallet_name}")
    except Exception as e:
        logger.error(f"Error in remove_wallet: {e}")

async def list_wallets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if user_id not in user_data or not user_data[user_id]['wallets']:
            await update.message.reply_text("📭 No tracked wallets.\n\nUse `/add <address> [name]`", parse_mode='Markdown')
            return
        
        wallets = user_data[user_id]['wallets']
        msg = f"📊 *Tracked Wallets ({len(wallets)}):*\n\n"
        
        for i, (address, name) in enumerate(wallets.items(), 1):
            short = f"{address[:6]}...{address[-6:]}"
            msg += f"{i}. 📛 *{name}*\n   `{short}`\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in list_wallets: {e}")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if user_id not in user_data:
            await update.message.reply_text("📊 No wallets tracked yet!")
            return
        
        count = len(user_data[user_id]['wallets'])
        msg = f"📊 *Statistics*\n\n👛 Tracked wallets: *{count}*\n⏱️ Check interval: *15 sec*"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in stats: {e}")

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if len(context.args) != 1:
            await update.message.reply_text("❌ Usage: `/balance <address>`", parse_mode='Markdown')
            return
        
        wallet_address = context.args[0].strip()
        await update.message.reply_text("⏳ Fetching...")
        
        balance_result = await get_wallet_balance(wallet_address)
        
        if not balance_result['success']:
            await update.message.reply_text(f"❌ Error: {balance_result.get('error')}")
            return
        
        await update.message.reply_text(
            f"💰 *Balance*\n\n`{wallet_address}`\n💵 *{balance_result['balance']:.4f} SOL*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in check_balance: {e}")

async def show_recent_transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        if len(context.args) != 1:
            await update.message.reply_text("❌ Usage: `/recent <address>`", parse_mode='Markdown')
            return
        
        wallet_address = context.args[0].strip()
        
        wallet_name = None
        if user_id in user_data and wallet_address in user_data[user_id]['wallets']:
            wallet_name = user_data[user_id]['wallets'][wallet_address]
        
        await update.message.reply_text("⏳ Fetching transactions...")
        
        tx_result = await get_recent_transactions(wallet_address, 5)
        
        if not tx_result['success']:
            await update.message.reply_text(f"❌ Error: {tx_result.get('error')}")
            return
        
        transactions = tx_result['transactions']
        
        if not transactions:
            await update.message.reply_text("📭 No recent transactions")
            return
        
        msg = "📜 *Recent Transactions*\n\n"
        if wallet_name:
            msg += f"📛 *{wallet_name}*\n\n"
        
        for i, tx in enumerate(transactions[:5], 1):
            sig = tx['signature']
            short_sig = f"{sig[:8]}...{sig[-8:]}"
            timestamp = datetime.fromtimestamp(tx['blockTime']).strftime('%Y-%m-%d %H:%M')
            status = "✅" if tx.get('err') is None else "❌"
            
            msg += f"{i}. {status} `{short_sig}`\n   ⏰ {timestamp}\n"
            
            tx_details = await get_transaction_details(sig)
            if tx_details['success']:
                transfers = parse_token_transfers(tx_details['transaction'], wallet_address)
                
                if transfers:
                    for transfer in transfers:
                        if transfer.get('is_sol'):
                            emoji = "📥" if transfer['type'] == 'RECEIVE' else "📤"
                            msg += f"   {emoji} {transfer['type']}: *{transfer['amount']:.4f} SOL*\n"
                        else:
                            token_info = await get_token_metadata(transfer['mint'])
                            symbol = token_info.get('symbol', 'UNKNOWN')
                            
                            if token_info.get('success') and not symbol.startswith('$'):
                                symbol = '$' + symbol
                            
                            emoji = "🟢" if transfer['type'] == 'BUY' else "🔴"
                            msg += f"   {emoji} {transfer['type']}: *{transfer['amount']:.4f} {symbol}*\n"
            
            msg += f"   🔗 [Solscan](https://solscan.io/tx/{sig})\n\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in show_recent: {e}")

# ============ MONITORING ============

async def monitor_wallets(application: Application):
    logger.info("🔍 Monitoring started...")
    
    while True:
        try:
            if not user_data:
                await asyncio.sleep(15)
                continue
            
            for user_id, data in list(user_data.items()):
                if not data.get('wallets'):
                    continue
                    
                for wallet_address, wallet_name in list(data['wallets'].items()):
                    try:
                        tx_result = await get_recent_transactions(wallet_address, 1)
                        
                        if not tx_result['success'] or not tx_result['transactions']:
                            continue
                        
                        latest_tx = tx_result['transactions'][0]
                        latest_sig = latest_tx['signature']
                        
                        last_known = data['last_signatures'].get(wallet_address)
                        
                        if last_known and latest_sig != last_known:
                            data['last_signatures'][wallet_address] = latest_sig
                            
                            timestamp = datetime.fromtimestamp(latest_tx['blockTime']).strftime('%Y-%m-%d %H:%M')
                            status = "✅" if latest_tx.get('err') is None else "❌"
                            
                            # Get transaction details FIRST
                            tx_details = await get_transaction_details(latest_sig)
                            transfers = []
                            
                            if tx_details['success']:
                                transfers = parse_token_transfers(tx_details['transaction'], wallet_address)
                            
                            # Build notification - TOKEN INFO FIRST (most important!)
                            notification = f"🔔 *New Transaction!*\n\n"
                            
                            # Show token movements PROMINENTLY at the top
                            if transfers:
                                for transfer in transfers:
                                    if transfer.get('is_sol'):
                                        emoji = "📥" if transfer['type'] == 'RECEIVE' else "📤"
                                        notification += f"{emoji} *{transfer['type']} {transfer['amount']:.4f} SOL*\n"
                                    else:
                                        # Get token symbol
                                        token_info = await get_token_metadata(transfer['mint'])
                                        symbol = token_info.get('symbol', 'UNKNOWN')
                                        
                                        # Add $ prefix if we found the real token
                                        if token_info.get('success') and not symbol.startswith('
                
                            
                            try:
                                await application.bot.send_message(
                                    chat_id=user_id,
                                    text=notification,
                                    parse_mode='Markdown',
                                    disable_web_page_preview=True
                                )
                                logger.info(f"Notification sent to {user_id} for {wallet_name}")
                            except Exception as e:
                                logger.error(f"Error sending notification: {e}")
                        
                        elif not last_known:
                            data['last_signatures'][wallet_address] = latest_sig
                    
                    except Exception as e:
                        logger.error(f"Error monitoring {wallet_address}: {e}")
                        continue
            
            await asyncio.sleep(15)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(30)

# ============ MAIN ============

async def post_init(application: Application):
    logger.info("🤖 Bot initialized!")
    
    # Load saved data at startup
    load_data()
    
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("add", "Add wallet to track"),
        BotCommand("remove", "Remove wallet"),
        BotCommand("list", "List tracked wallets"),
        BotCommand("balance", "Check wallet balance"),
        BotCommand("recent", "Show recent transactions"),
        BotCommand("stats", "Show statistics"),
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Commands set")
    except Exception as e:
        logger.error(f"Error setting commands: {e}")
    
    asyncio.create_task(monitor_wallets(application))

def main():
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("❌ Set TELEGRAM_BOT_TOKEN environment variable!")
        return
    
    logger.info("🚀 Starting bot...")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("recent", show_recent_transactions))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.post_init = post_init
    
    logger.info("🤖 Bot starting...")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("🛑 Stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    main()):
                                            symbol = '
                
                            
                            try:
                                await application.bot.send_message(
                                    chat_id=user_id,
                                    text=notification,
                                    parse_mode='Markdown',
                                    disable_web_page_preview=True
                                )
                                logger.info(f"Notification sent to {user_id} for {wallet_name}")
                            except Exception as e:
                                logger.error(f"Error sending notification: {e}")
                        
                        elif not last_known:
                            data['last_signatures'][wallet_address] = latest_sig
                    
                    except Exception as e:
                        logger.error(f"Error monitoring {wallet_address}: {e}")
                        continue
            
            await asyncio.sleep(15)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(30)

# ============ MAIN ============

async def post_init(application: Application):
    logger.info("🤖 Bot initialized!")
    
    # Load saved data at startup
    load_data()
    
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("add", "Add wallet to track"),
        BotCommand("remove", "Remove wallet"),
        BotCommand("list", "List tracked wallets"),
        BotCommand("balance", "Check wallet balance"),
        BotCommand("recent", "Show recent transactions"),
        BotCommand("stats", "Show statistics"),
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Commands set")
    except Exception as e:
        logger.error(f"Error setting commands: {e}")
    
    asyncio.create_task(monitor_wallets(application))

def main():
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("❌ Set TELEGRAM_BOT_TOKEN environment variable!")
        return
    
    logger.info("🚀 Starting bot...")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("recent", show_recent_transactions))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.post_init = post_init
    
    logger.info("🤖 Bot starting...")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("🛑 Stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    main() + symbol
                                        
                                        emoji = "🟢" if transfer['type'] == 'BUY' else "🔴"
                                        notification += f"{emoji} *{transfer['type']} {transfer['amount']:.4f} {symbol}*\n"
                                notification += "\n"
                            
                            # Then add wallet name and details
                            notification += f"📛 *{wallet_name}*\n"
                            notification += f"Status: {status}\n"
                            notification += f"Time: {timestamp}\n"
                            notification += f"🔗 [View Transaction](https://solscan.io/tx/{latest_sig})"
                
                            
                            try:
                                await application.bot.send_message(
                                    chat_id=user_id,
                                    text=notification,
                                    parse_mode='Markdown',
                                    disable_web_page_preview=True
                                )
                                logger.info(f"Notification sent to {user_id} for {wallet_name}")
                            except Exception as e:
                                logger.error(f"Error sending notification: {e}")
                        
                        elif not last_known:
                            data['last_signatures'][wallet_address] = latest_sig
                    
                    except Exception as e:
                        logger.error(f"Error monitoring {wallet_address}: {e}")
                        continue
            
            await asyncio.sleep(15)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(30)

# ============ MAIN ============

async def post_init(application: Application):
    logger.info("🤖 Bot initialized!")
    
    # Load saved data at startup
    load_data()
    
    commands = [
        BotCommand("start", "Start the bot"),
        BotCommand("add", "Add wallet to track"),
        BotCommand("remove", "Remove wallet"),
        BotCommand("list", "List tracked wallets"),
        BotCommand("balance", "Check wallet balance"),
        BotCommand("recent", "Show recent transactions"),
        BotCommand("stats", "Show statistics"),
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Commands set")
    except Exception as e:
        logger.error(f"Error setting commands: {e}")
    
    asyncio.create_task(monitor_wallets(application))

def main():
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("❌ Set TELEGRAM_BOT_TOKEN environment variable!")
        return
    
    logger.info("🚀 Starting bot...")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("recent", show_recent_transactions))
    application.add_handler(CommandHandler("stats", stats_command))
    
    application.post_init = post_init
    
    logger.info("🤖 Bot starting...")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("🛑 Stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    main()
