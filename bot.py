import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, CallbackContext

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

# 📌 Step 6: Handle Month Selection & Show Stats
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

    # Format the summary message
    stats_msg = f"📊 **{selected_month} Summary** 📊\n\n"
    stats_msg += "💸 **Expenses:**\n" + ("\n".join(expense_list) if expense_list else "No expenses") + "\n\n"
    stats_msg += "💰 **Incomes:**\n" + ("\n".join(income_list) if income_list else "No income") + "\n\n"
    stats_msg += f"📉 **Total Expenses:** ${expenses:.2f}\n"
    stats_msg += f"📈 **Total Income:** ${incomes:.2f}\n"
    stats_msg += f"💵 **Net Balance:** ${incomes - expenses:.2f}"

    await query.message.reply_text(stats_msg)
    await query.answer()
    
# 📌 Handle /delete Command
async def delete_transaction(update: Update, context: CallbackContext) -> None:
    user_id = update.message.from_user.id
    
    # Fetch the last 5 transactions of the user
    cursor.execute("""
        SELECT id, type, category, account, amount, date FROM transactions
        WHERE user_id = ?
        ORDER BY date DESC
        LIMIT 5
    """, (user_id,))
    transactions = cursor.fetchall()

    if not transactions:
        await update.message.reply_text("❌ No transactions found to delete.")
        return

    # Generate buttons for each transaction
    keyboard = [
        [InlineKeyboardButton(f"{t[1].capitalize()} - {t[2]} - ${t[4]:.2f} [{t[3]}]", callback_data=f"delete_{t[0]}")]
        for t in transactions
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text("🗑 Select a transaction to delete:", reply_markup=reply_markup)

# 📌 Handle Delete Confirmation
async def confirm_delete(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    txn_id = query.data.split("_")[1]

    # Remove transaction from database
    cursor.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
    conn.commit()

    await query.message.reply_text("✅ Transaction deleted successfully.")
    await query.answer()

# 📌 Step 7: Start Bot
TOKEN = "7874129479:AAGYxPf59PgFcYL8-e33tSZAA9UOGzqFw9k"
app = Application.builder().token(TOKEN).build()

# Command Handlers
app.add_handler(CommandHandler("spend", spend))
app.add_handler(CommandHandler("save", save))
app.add_handler(CommandHandler("stats", stats))
app.add_handler(CommandHandler("delete", delete_transaction))

# Callback Query Handlers
app.add_handler(CallbackQueryHandler(category_callback, pattern="^category_"))
app.add_handler(CallbackQueryHandler(account_callback, pattern="^account_"))
app.add_handler(CallbackQueryHandler(month_callback, pattern="^month_"))
app.add_handler(CallbackQueryHandler(confirm_delete, pattern="^delete_"))

# Start Bot
print("🤖 Bot is running...")
app.run_polling()
