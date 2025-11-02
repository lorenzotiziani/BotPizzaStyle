import os
import smtplib
import uuid
import psycopg
from email.message import EmailMessage
from functools import wraps
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, Bot
from telegram.ext import ContextTypes, CallbackContext

# PostgreSQL connection
conn = psycopg.connect(os.getenv("DATABASE_URL"))

# === DECORATOR ===
def only_registered(func):
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id

        cursor = conn.cursor()
        cursor.execute("SELECT active FROM \"User\" WHERE telegramId = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()

        if not row or row[0] != 1:
            if hasattr(update, "message") and update.message:
                await update.message.reply_text("⛔ Non sei autorizzato. Registrati prima.")
            elif hasattr(update, "inline_query") and update.inline_query:
                await update.inline_query.answer([], cache_time=0)
            return  # Blocca l'accesso

        return await func(update, context, *args, **kwargs)
    return wrapper


# === COMMAND HANDLERS ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Ciao! Per utilizzare gli altri comandi devi registrarti e attendere l'approvazione dell'admin :)"
    )


async def getID(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(f"Il tuo user ID è: {user_id}")


@only_registered
async def inlinequery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query:
        return

    cursor = conn.cursor()
    cursor.execute(
        "SELECT indirizzo, mapsLink FROM \"Indirizzo\" WHERE indirizzo ILIKE %s LIMIT 10",
        (f"%{query}%",)
    )
    results = cursor.fetchall()
    cursor.close()

    inline_results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=row[0],
            input_message_content=InputTextMessageContent(f"{row[0]}\n{row[1]}"),
            description=row[1]
        )
        for row in results
    ]

    await update.inline_query.answer(inline_results, cache_time=1)


@only_registered
async def check_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.startswith("@PizzaStylePonyBot"):
        await update.message.reply_text(
            "Per cercare indirizzi in tempo reale, scrivi iniziando con @PizzaStylePonyBot"
        )
        return

    query = text[len("@PizzaStylePonyBot"):].strip()
    await update.message.reply_text(f"Hai cercato: {query}")


# === REGISTRAZIONE ===
def salva_utente_e_invia_mail(user_id: int, nome: str):
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO "User" (telegramId, nominativo, active, notified)
        VALUES (%s, %s, false, false)
    """, (user_id, nome))
    conn.commit()
    cursor.close()

    # Invia mail admin
    admin_email = os.getenv("ADMIN_EMAIL")
    email_user = os.getenv("EMAIL_USER")
    email_password = os.getenv("EMAIL_PASSWORD")

    msg = EmailMessage()
    msg['Subject'] = "Nuovo utente da approvare"
    msg['From'] = email_user
    msg['To'] = admin_email
    msg.set_content(f"L'utente {nome} ({user_id}) ha richiesto accesso al bot.\nAggiorna il campo 'active' nel DB.")

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(email_user, email_password)
        smtp.send_message(msg)


async def registra_utente(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    nome = update.effective_user.username or "Utente"

    cursor = conn.cursor()
    cursor.execute('SELECT telegramId, active FROM "User" WHERE telegramId = %s', (user_id,))
    row = cursor.fetchone()
    cursor.close()

    if row:
        if row[1] == 0:
            await update.message.reply_text("⏳ Attendi che l'admin approvi la tua registrazione.")
            return
        elif row[1] == 1:
            await update.message.reply_text("✅ Sei già registrato e approvato.")
            return
    else:
        salva_utente_e_invia_mail(user_id, nome)
        await update.message.reply_text(
            "📨 Richiesta inviata all'amministratore. Riceverai un messaggio quando sarai autorizzato."
        )


# === CONTROLLO PERIODICO ===
async def verifica_utenti_autorizzati(bot: Bot):
    import asyncio
    while True:
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT telegramId, nominativo FROM "User" WHERE active = true AND notified = false')
            results = cursor.fetchall()

            for user_id, nome in results:
                try:
                    await bot.send_message(chat_id=user_id, text=f"Ciao {nome}! Ora sei autorizzato a usare il bot 🎉")
                    cursor.execute('UPDATE "User" SET notified = true WHERE telegramId = %s', (user_id,))
                except Exception as e:
                    print(f"Errore invio messaggio a {user_id}: {e}")

            conn.commit()
            cursor.close()

        except Exception as e:
            print(f"Errore verifica utenti autorizzati: {e}")

        await asyncio.sleep(30)


async def lista_utenti(update: Update, context: CallbackContext):
    if update.effective_user.id != int(os.getenv("ADMIN_ID")):
        await update.message.reply_text("⛔ Non sei autorizzato a usare questo comando.")
        return

    try:
        cursor = conn.cursor()
        cursor.execute('SELECT telegram_id, nome, active FROM "User" WHERE active = false')
        results = cursor.fetchall()
        cursor.close()

        if not results:
            await update.message.reply_text("✅ Tutti gli utenti sono già approvati.")
            return

        # Costruisci il messaggio
        message = "👥 *Utenti in attesa di approvazione:*\n\n"
        for telegram_id, nome, active in results:
            message += f"• `{telegram_id}` — {nome}\n"

        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        print(f"Errore in lista_utenti: {e}")
        await update.message.reply_text("❌ Errore durante il recupero della lista utenti.")

async def conferma_utenti(update: Update, context: CallbackContext):
    if update.effective_user.id != int(os.getenv("ADMIN_ID")):
        await update.message.reply_text("⛔ Non sei autorizzato a usare questo comando.")
        return

    try:
        user_id = int(context.args[0])

        cursor = conn.cursor()
        cursor.execute('SELECT telegramId FROM "User" WHERE telegramId = %s', (user_id,))
        row = cursor.fetchone()

        if not row:
            await update.message.reply_text("⚠️ Nessun utente trovato con questo ID.")
        else:
            cursor.execute(
                'UPDATE "User" SET active = true, notified = false WHERE telegramId = %s',
                (user_id,)
            )
            conn.commit()
            await update.message.reply_text(f"✅ Utente {user_id} approvato correttamente.")
        cursor.close()

    except ValueError:
        await update.message.reply_text("❗ L'ID deve essere un numero.")
    except Exception as e:
        print(f"Errore in conferma_utenti: {e}")
        await update.message.reply_text("❌ Errore durante l'approvazione dell'utente.")
