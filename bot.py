import logging
import os
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, InlineQueryHandler
from functions import start, getID, registra_utente, inlinequery, verifica_utenti_autorizzati,check_inline,lista_utenti,conferma_utenti
import asyncio

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

async def on_startup(application):
    # Avvia il task ricorrente all'interno del loop già attivo
    asyncio.create_task(verifica_utenti_autorizzati(application.bot))

if __name__ == "__main__":
    application = ApplicationBuilder().token(os.getenv("APIBOT")).build()

    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", getID))
    application.add_handler(CommandHandler("indirizzi", check_inline))
    application.add_handler(CommandHandler("register", registra_utente))
    application.add_handler(CommandHandler("listaUtenti", lista_utenti))
    application.add_handler(CommandHandler("confermaUtenti", conferma_utenti))
    application.add_handler(InlineQueryHandler(inlinequery))

    # Callback di startup per lanciare task ricorrente
    application.post_init = on_startup

    logging.info("Bot in esecuzione...")
    application.run_polling()
