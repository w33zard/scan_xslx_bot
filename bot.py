"""
Telegram-бот для извлечения данных из сканов паспортов
Отправьте ZIP или папку с изображениями паспортов — бот вернёт Excel
"""
import asyncio
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from excel_export import create_excel
from ocr_extractor import process_passport_image, process_images_from_folder

ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "1847615831").split(",") if x.strip()]


def admin_only(func):
    """Доступ только для админов"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if ADMIN_IDS and user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ Доступ запрещён.")
            return
        return await func(update, context)
    return wrapper


@admin_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Приветственное сообщение"""
    await update.message.reply_text(
        "👋 Привет! Я бот для извлечения данных из сканов паспортов.\n\n"
        "📤 Отправьте мне:\n"
        "• ZIP-архив с изображениями паспортов (.jpg, .png и т.д.)\n"
        "• Или несколько фото паспортов, затем /ready\n\n"
        "📊 Я обработаю сканы через OCR и верну Excel-файл с данными:\n"
        "ФИО, дата рождения, место рождения, серия и номер, дата выдачи, кем выдан, ИНН, адрес.\n\n"
        "⚠️ Требования: чёткие фото, хорошее освещение. Поддержка русского языка."
    )


@admin_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка ZIP-архива"""
    document = update.message.document
    if not document.file_name.lower().endswith(".zip"):
        await update.message.reply_text(
            "⚠️ Пожалуйста, отправьте ZIP-архив с изображениями паспортов."
        )
        return

    await update.message.reply_text("📥 Получаю архив...")

    try:
        file = await context.bot.get_file(document.file_id)
        zip_path = os.path.join(tempfile.gettempdir(), f"passports_{document.file_unique_id}.zip")
        await file.download_to_drive(zip_path)

        extract_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            await update.message.reply_text("🔍 Обрабатываю изображения (OCR)...")

            results = process_images_from_folder(extract_dir)

            if not results:
                await update.message.reply_text(
                    "❌ В архиве не найдено изображений (jpg, png, bmp, tiff)."
                )
                return

            output_path = os.path.join(tempfile.gettempdir(), "passports_data.xlsx")
            template = os.environ.get("TEMPLATE_EXCEL")
            create_excel(results, output_path, template_excel=template)

            await update.message.reply_text(
                f"✅ Обработано паспортов: {len(results)}"
            )
            with open(output_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="passports_data.xlsx",
                )
            os.unlink(output_path)
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.unlink(zip_path)

    except zipfile.BadZipFile:
        await update.message.reply_text("❌ Ошибка: повреждённый ZIP-архив.")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")


@admin_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка фото — сохраняем в контекст и ждём /готово или следующее фото"""
    if "pending_photos" not in context.user_data:
        context.user_data["pending_photos"] = []

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    photo_path = os.path.join(tempfile.gettempdir(), f"photo_{photo.file_unique_id}.jpg")
    await file.download_to_drive(photo_path)
    context.user_data["pending_photos"].append(photo_path)

    count = len(context.user_data["pending_photos"])
    await update.message.reply_text(
        f"📷 Получено фото: {count}. Отправьте ещё или введите /ready для обработки."
    )


@admin_only
async def process_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка накопленных фото по команде /готово"""
    photos = context.user_data.get("pending_photos", [])
    if not photos:
        await update.message.reply_text(
            "📷 Сначала отправьте фото паспортов, затем /ready"
        )
        return

    await update.message.reply_text("🔍 Обрабатываю изображения (OCR)...")

    results = []
    for i, path in enumerate(photos, 1):
        try:
            row = process_passport_image(path, index=i)
            results.append(row)
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

    context.user_data["pending_photos"] = []

    output_path = os.path.join(tempfile.gettempdir(), "passports_data.xlsx")
    template = os.environ.get("TEMPLATE_EXCEL")
    create_excel(results, output_path, template_excel=template)

    await update.message.reply_text(f"✅ Обработано паспортов: {len(results)}")
    with open(output_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename="passports_data.xlsx",
        )
    os.unlink(output_path)


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Установите переменную окружения TELEGRAM_BOT_TOKEN")
        print("Получить токен: https://t.me/BotFather")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ready", process_ready))
    app.add_handler(
        MessageHandler(filters.Document.ALL, handle_document)
    )
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
