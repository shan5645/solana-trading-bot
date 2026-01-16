chat_id=user_id,
                                    text=notification,
                                    parse_mode='Markdown',
                                    disable_web_page_preview=True
                                )
                                logger.info(f"Sent notification to user {user_id} for wallet {wallet_name}")
                            except Exception as e:
                                logger.error(f"Error sending notification to user {user_id}: {e}")
                        
                        elif not last_known_signature:
                            # First time seeing this wallet, just record the signature
                            data['last_signatures'][wallet_address] = latest_signature
                    
                    except Exception as e:
                        logger.error(f"Error monitoring wallet {wallet_address}: {e}")
                        continue
            
            # Wait 15 seconds before next check
            await asyncio.sleep(15)
            
        except Exception as e:
            logger.error(f"Error in monitoring loop: {e}")
            await asyncio.sleep(30)

# ============ MAIN FUNCTION ============

async def post_init(application: Application):
    """Initialize the bot after startup"""
    logger.info("🤖 Bot initialized successfully!")
    
    # Set bot commands
    commands = [
        BotCommand("start", "Start the bot and see welcome message"),
        BotCommand("help", "Show help message"),
        BotCommand("add", "Add a wallet to track"),
        BotCommand("rename", "Rename a tracked wallet"),
        BotCommand("remove", "Remove a wallet from tracking"),
        BotCommand("list", "List all tracked wallets"),
        BotCommand("balance", "Check wallet balance"),
        BotCommand("recent", "Show recent transactions"),
        BotCommand("stats", "Show your statistics"),
    ]
    
    try:
        await application.bot.set_my_commands(commands)
        logger.info("✅ Bot commands set successfully")
    except Exception as e:
        logger.error(f"Error setting bot commands: {e}")
    
    # Start the monitoring task
    asyncio.create_task(monitor_wallets(application))

def main():
    """Start the bot"""
    
    if TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE':
        logger.error("❌ ERROR: Please set your TELEGRAM_BOT_TOKEN environment variable!")
        logger.error("Get your token from @BotFather on Telegram")
        return
    
    logger.info("🚀 Starting Solana Wallet Tracker Bot...")
    
    # Create the Application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add", add_wallet))
    application.add_handler(CommandHandler("rename", rename_wallet))
    application.add_handler(CommandHandler("remove", remove_wallet))
    application.add_handler(CommandHandler("list", list_wallets))
    application.add_handler(CommandHandler("balance", check_balance))
    application.add_handler(CommandHandler("recent", show_recent_transactions))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Set post_init callback
    application.post_init = post_init
    
    # Start the bot
    logger.info("🤖 Bot is starting...")
    logger.info("Press Ctrl+C to stop")
    
    try:
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    main()
