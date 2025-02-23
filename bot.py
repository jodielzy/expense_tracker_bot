import os
import sqlite3
import logging
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext

# Define a simple health check endpoint
async def health(request):
    return web.Response(text="Bot is running", status=200)

# Create a custom aiohttp application
custom_app = web.Application()
custom_app.router.add_get('/', health)

# Enable logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

# Database Setup
conn = sqlite3.connect("expenses.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    category TEXT,
    description TEXT,
    type TEXT,  -- 'expense' or 'income'
    month TEXT DEFAULT 'January'
)
""")
conn.commit()

# Predefined lists
CATEGORIES = ["F&B", "Transport", "Necessities", "Social", "Education", "Shopping", "Others"]
ACCOUNTS = ["OCBC", "Standard Chartered", "Cash", "Webull"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

default_month = "January"  # Global fallback for month

# Retrieve configuration from environment variables
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7874129479:AAGYxPf59PgFcYL8-e33tSZAA9UOGzqFw9k")
PORT = int(os.environ.get("PORT", "8443"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://expense-tracker-bot-fe4a.onrender.com")  # Must start with "https://"

# Initialize Bot Application
app = Application.builder().token(BOT_TOKEN).build()

# /start Command
async def start(update: Update, context: CallbackContext) -> None:
    message = """🤖 Welcome to Piggy Bank Bot! Here are the features:

📌 Record expenses: /spend <amount> <description>
💾 Record savings: /save <amount> <description>
📊 View stats: /stats
🗑 Delete previous entry: /delete
🔄 Change month: /change
"""
    await update.message.reply_text(message)

# /change Command
async def change(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton(month, callback_data=f"changeall_{month}")] for month in MONTHS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📅 Select the new month:", reply_markup=reply_markup)

async def change_all_transactions_callback(update: Update, context: CallbackContext) -> None:
    global default_month  # Declare global at the start of the function
    query = update.callback_query
    new_month = query.data.split("_")[1]
    user_id = query.from_user.id
    # Get the current month from user's data if set; otherwise use the global default_month
    current_month = context.user_data.get('current_month', default_month)
    
    # Calculate net balance for the current month:
    cursor.execute("""
        SELECT type, amount FROM transactions
        WHERE user_id = ? AND month = ?
    """, (user_id, current_month))
    transactions = cursor.fetchall()
    net_balance = 0
    for txn_type, amount in transactions:
        if txn_type == "income":
            net_balance += amount
        else:  # expense
            net_balance -= amount

    # Check if a carry-forward record already exists for the new month
    cursor.execute("""
        SELECT id FROM transactions
        WHERE user_id = ? AND month = ? AND category = ?
    """, (user_id, new_month, "Carry Forward"))
    carry_forward_exists = cursor.fetchone() is not None

    if not carry_forward_exists and net_balance != 0:
        # If net_balance is positive, record it as an income; if negative, as an expense.
        carry_type = "income" if net_balance > 0 else "expense"
        cursor.execute("""
            INSERT INTO transactions (user_id, amount, category, description, type, month)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, abs(net_balance), "Carry Forward",
              f"Carried forward net balance from {current_month}", carry_type, new_month))
        conn.commit()

    # Update the user's current month preference
    context.user_data['current_month'] = new_month
    default_month = new_month

    await query.message.reply_text(f"✅ Month changed to {new_month}. Net savings carried forward: {net_balance:.2f}")
    await query.answer()

# /spend Command
async def spend(update: Update, context: CallbackContext) -> None:
    try:
        amount = float(context.args[0])
        description = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        context.user_data['amount'] = amount
        context.user_data['description'] = description

        # Ask user to select a category
        keyboard = [[InlineKeyboardButton(cat, callback_data=f"category_{cat}")] for cat in CATEGORIES]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📌 Select a category for your expense:", reply_markup=reply_markup)
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /spend <amount> <description>")

# Callback: when a category is selected for spending
async def category_selected(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    category = query.data.split("_")[1]
    context.user_data['category'] = category

    # Now ask for the account selection
    keyboard = [[InlineKeyboardButton(acc, callback_data=f"account_{acc}")] for acc in ACCOUNTS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.message.reply_text("🏦 Select the account for your expense:", reply_markup=reply_markup)
    await query.answer()

# Callback: when an account is selected (after category selection)
async def account_selected(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    account = query.data.split("_")[1]
    user_id = query.from_user.id
    amount = context.user_data.get('amount')
    category = context.user_data.get('category')
    description = context.user_data.get('description')
    # Use the user-specific current month if available
    current_month = context.user_data.get('current_month', default_month)

    cursor.execute(
        "INSERT INTO transactions (user_id, amount, category, description, type, month) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, amount, f"{category} ({account})", description, "expense", current_month)
    )
    conn.commit()

    await query.message.reply_text(
        f"✅ Expense recorded: ${amount} in {category} from {account} for {current_month}. Description: {description}"
    )
    await query.answer()

# /save Command
async def save(update: Update, context: CallbackContext) -> None:
    try:
        amount = float(context.args[0])
        description = " ".join(context.args[1:]) if len(context.args) > 1 else ""
        context.user_data['amount'] = amount
        context.user_data['description'] = description

        # Ask user to select the account for savings
        keyboard = [[InlineKeyboardButton(acc, callback_data=f"save_account_{acc}")] for acc in ACCOUNTS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🏦 Select the account for savings:", reply_markup=reply_markup)
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /save <amount> <description>")

# Callback: when an account is selected for savings
async def save_account_selected(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    account = query.data.split("_")[2]
    user_id = query.from_user.id
    amount = context.user_data.get('amount')
    description = context.user_data.get('description')
    current_month = context.user_data.get('current_month', default_month)

    cursor.execute(
        "INSERT INTO transactions (user_id, amount, category, description, type, month) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, amount, f"Savings ({account})", description, "income", current_month)
    )
    conn.commit()

    await query.message.reply_text(
        f"✅ Savings recorded: ${amount} into {account} for {current_month}. Description: {description}"
    )
    await query.answer()

# /stats Command
async def stats(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    current_month = context.user_data.get('current_month', default_month)
    logging.info(f"Stats requested for month: {current_month}")

    cursor.execute("""
        SELECT type, category, amount, description FROM transactions
        WHERE user_id = ? AND month = ?
    """, (user_id, current_month))
    transactions = cursor.fetchall()

    if not transactions:
        await update.message.reply_text(f"📊 No transactions found for {current_month}.")
        return

    expenses, incomes = 0, 0
    txn_list = []

    for txn_type, category, amount, description in transactions:
        if txn_type == "expense":
            expenses += amount
            txn_list.append(f"📉 {category}: -${amount:.2f} | {description}")
        else:
            incomes += amount
            txn_list.append(f"💰 {category}: +${amount:.2f} | {description}")

    net_balance = incomes - expenses

    stats_msg = f"📊 **Transaction History for {current_month}** 📊\n\n"
    stats_msg += "\n".join(txn_list) + "\n\n"
    stats_msg += f"💰 **Total Income:** ${incomes:.2f}\n"
    stats_msg += f"📉 **Total Expenses:** ${expenses:.2f}\n"
    stats_msg += f"💵 **Net Balance:** ${net_balance:.2f}"

    await update.message.reply_text(stats_msg)

# /delete Command
async def delete_transaction(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    cursor.execute("SELECT id FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,))
    row = cursor.fetchone()
    if row:
        txn_id = row[0]
        cursor.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        conn.commit()
        await update.message.reply_text("✅ Last transaction deleted.")
    else:
        await update.message.reply_text("❌ No transaction found to delete.")

# Register Handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("spend", spend))
app.add_handler(CommandHandler("save", save))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("delete", delete_transaction))
app.add_handler(CommandHandler("change", change))
app.add_handler(CallbackQueryHandler(category_selected, pattern="^category_"))
app.add_handler(CallbackQueryHandler(account_selected, pattern="^account_"))
app.add_handler(CallbackQueryHandler(save_account_selected, pattern="^save_account_"))
app.add_handler(CallbackQueryHandler(change_all_transactions_callback, pattern="^changeall_"))

# Run the bot as a web service using the custom app with the GET route
if __name__ == "__main__":
    import asyncio

    loop = asyncio.get_event_loop()
    loop.create_task(
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=BOT_TOKEN,
            webhook_url=WEBHOOK_URL + "/" + BOT_TOKEN,
            app=custom_app  # Passing the custom app with the health check route
        )
    )
    print("🤖 Bot is running...")
    loop.run_forever()

