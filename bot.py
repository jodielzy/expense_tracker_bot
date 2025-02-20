import sqlite3
import logging
import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler

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
    account TEXT,
    type TEXT,  -- 'expense' or 'income'
    date TEXT DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Predefined lists for category & account selection
CATEGORIES = ["F&B", "Transport", "Necessities", "Social", "Education", "Shopping", "Others"]
ACCOUNTS = ["OCBC", "Standard Chartered", "Cash", "Webull"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]

# Store temporary user input
user_data = {}

# 📌 Step 1: Handle /spend Command
async def spend(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.message.from_user.id
        amount = float(context.args[0])
        user_data[user_id] = {"amount": amount, "type": "expense"}

        # Show category selection
        keyboard = [[InlineKeyboardButton(cat, callback_data=f"category_{cat}")] for cat in CATEGORIES]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📌 Select a category:", reply_markup=reply_markup)

    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /spend <amount> <description>")

# 📌 Step 2: Handle /save Command
async def save(update: Update, context: CallbackContext) -> None:
    try:
        user_id = update.message.from_user.id
        amount = float(context.args[0])
        user_data[user_id] = {"amount": amount, "type": "income"}

        # Show account selection
        keyboard = [[InlineKeyboardButton(acc, callback_data=f"account_{acc}")] for acc in ACCOUNTS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("🏦 Select an account:", reply_markup=reply_markup)

    except (IndexError, ValueError):
        await update.message.reply_text("❌ Usage: /save <amount> <description>")

# 📌 Step 3: Handle Category Selection
async def category_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    category = query.data.split("_")[1]

    if user_id in user_data:
        user_data[user_id]["category"] = category

        # Show account selection
        keyboard = [[InlineKeyboardButton(acc, callback_data=f"account_{acc}")] for acc in ACCOUNTS]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text("🏦 Select an account:", reply_markup=reply_markup)
    await query.answer()

# 📌 Step 4: Handle Account Selection
async def account_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    account = query.data.split("_")[1]

    if user_id in user_data:
        amount = user_data[user_id]["amount"]
        txn_type = user_data[user_id]["type"]
        category = user_data[user_id].get("category", "N/A")

        # Store transaction in the database
        cursor.execute("INSERT INTO transactions (user_id, amount, category, account, type) VALUES (?, ?, ?, ?, ?)",
                       (user_id, amount, category, account, txn_type))
        conn.commit()

        txn_text = f"✅ {txn_type.capitalize()} Recorded:\n💰 Amount: ${amount}\n📌 Category: {category}\n🏦 Account: {account}"
        await query.message.reply_text(txn_text)
        del user_data[user_id]  # Clear temporary data
    await query.answer()

# 📌 Step 5: Handle /stats Command
async def stats(update: Update, context: CallbackContext) -> None:
    keyboard = [[InlineKeyboardButton(month, callback_data=f"month_{month}")] for month in MONTHS]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📆 Select a month:", reply_markup=reply_markup)

# 📌 Step 6: Handle Month Selection & Show Stats (With Carry Forward Savings)
async def month_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    selected_month = query.data.split("_")[1]

    # Fetch transactions for selected month
    cursor.execute("""
        SELECT type, category, account, amount FROM transactions
        WHERE user_id = ? AND strftime('%m', date) = ?
    """, (user_id, f"{MONTHS.index(selected_month)+1:02}"))
    transactions = cursor.fetchall()

    # Fetch previous balance
    cursor.execute("""
        SELECT SUM(CASE WHEN type='income' THEN amount ELSE -amount END)
        FROM transactions WHERE user_id = ? AND strftime('%m', date) < ?
    """, (user_id, f"{MONTHS.index(selected_month)+1:02}"))
    previous_balance = cursor.fetchone()[0] or 0

    # Generate stats
    expenses, incomes = 0, 0
    expense_list, income_list = [], []

    for txn_type, category, account, amount in transactions:
        if txn_type == "expense":
            expenses += amount
            expense_list.append(f"- {category} (${amount}) [{account}]")
        else:
            incomes += amount
            income_list.append(f"+ {category} (${amount}) [{account}]")

    final_balance = previous_balance + (incomes - expenses)

    # Format the summary message
    stats_msg = f"📊 **{selected_month} Summary** 📊\n\n"
    stats_msg += f"💾 **Previous Savings:** ${previous_balance:.2f}\n"
    stats_msg += f"💰 **Total Income:** ${incomes:.2f}\n"
    stats_msg += f"📉 **Total Expenses:** ${expenses:.2f}\n"
    stats_msg += f"💵 **Net Balance (incl. previous savings):** ${final_balance:.2f}"

    await query.message.reply_text(stats_msg)
    await query.answer()

# 📌 Step 7: Automatically Carry Forward Balance Every Month
def carry_forward_balance():
    today = datetime.date.today()
    first_day_of_month = today.replace(day=1)
    last_month = first_day_of_month - datetime.timedelta(days=1)
    last_month_str = last_month.strftime('%m')

    cursor.execute("""
        SELECT user_id, SUM(CASE WHEN type='income' THEN amount ELSE -amount END)
        FROM transactions WHERE strftime('%m', date) = ?
        GROUP BY user_id
    """, (last_month_str,))
    user_balances = cursor.fetchall()

    for user_id, balance in user_balances:
        if balance != 0:
            cursor.execute("""
                INSERT INTO transactions (user_id, amount, category, account, type, date)
                VALUES (?, ?, 'Carry Forward', 'Previous Balance', 'income', ?)
            """, (user_id, balance, today.strftime('%Y-%m-%d')))
    
    conn.commit()

scheduler = BackgroundScheduler()
scheduler.add_job(carry_forward_balance, 'cron', day=1, hour=0, minute=0)
scheduler.start()

# Start Bot
TOKEN = "7874129479:AAGYxPf59PgFcYL8-e33tSZAA9UOGzqFw9k"
app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("spend", spend))
app.add_handler(CommandHandler("save", save))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CallbackQueryHandler(category_callback, pattern="^category_"))
app.add_handler(CallbackQueryHandler(account_callback, pattern="^account_"))
app.add_handler(CallbackQueryHandler(month_callback, pattern="^month_"))

print("🤖 Bot is running...")
app.run_polling()
