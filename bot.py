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
async def cmd_test(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Проверка парсинга — убедиться, что логика работает"""
    from ocr_extractor import parse_passport_data
    sample = "ЦИЦАР\nФамилия\nФЕДОР\nИмя\nМИХАЙЛОВИЧ\nОтчество\n03.04.1987\n4008 595794"
    data = parse_passport_data(sample)
    fio = data.get("Фамилия") and data.get("Имя") and data.get("Отчество")
    series = data.get("Серия и номер паспорта")
    if fio and series:
        await update.message.reply_text(
            f"✅ Парсинг работает.\nФИО: {data['Фамилия']} {data['Имя']} {data['Отчество']}\nСерия: {series}"
        )
    else:
        await update.message.reply_text(f"❌ Парсинг не извлёк данные. Получено: {data}")


@admin_only
async def cmd_diagnose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Полная диагностика: Yandex, Tesseract, OCR, парсинг"""
    lines = []
    # 1. Yandex key
    key = os.environ.get("YANDEX_VISION_API_KEY", "")
    lines.append(f"1. Yandex API: {'✅ ключ есть' if key else '❌ ключ НЕ задан'}")

    # 2. Tesseract
    try:
        import pytesseract
        v = pytesseract.get_tesseract_version()
        lines.append(f"2. Tesseract: ✅ {v}")
    except Exception as e:
        lines.append(f"2. Tesseract: ❌ не установлен ({e})")

    # 3. Создаём тестовое изображение и запускаем OCR
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (600, 200), "white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "ЦИЦАР ФЕДОР 4008 595794", fill="black")
        path = os.path.join(tempfile.gettempdir(), "diag_test.jpg")
        img.save(path, "JPEG")

        from ocr_extractor import extract_text_from_image, parse_passport_data
        ocr = extract_text_from_image(path)
        lines.append(f"3. OCR: {len(ocr)} символов")
        if ocr:
            lines.append(f"   Текст: {ocr[:150]}...")
        else:
            lines.append("   ❌ OCR пустой — ни Yandex, ни Tesseract не вернули текст")

        data = parse_passport_data(ocr or "")
        fio = data.get("Фамилия") or data.get("Имя") or data.get("Отчество")
        series = data.get("Серия и номер паспорта")
        lines.append(f"4. Парсинг: ФИО={bool(fio)}, Серия={series or 'пусто'}")
        try:
            os.unlink(path)
        except Exception:
            pass
    except Exception as e:
        lines.append(f"3-4. Ошибка: {e}")

    await update.message.reply_text("🔍 Диагностика:\n\n" + "\n".join(lines))


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
        "⚠️ Требования: чёткие фото, хорошее освещение. Поддержка русского языка.\n\n"
        "🔧 /diagnose — проверка OCR и зависимостей\n"
        "🔍 /ocr_raw — отправить фото и получить сырой OCR + разбор (отладка)"
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

            empty_count = sum(1 for r in results if not r.get("Фамилия") and not r.get("Серия и номер паспорта"))
            if empty_count == len(results) and results:
                await update.message.reply_text(
                    "⚠️ OCR не распознал данные ни в одном паспорте. "
                    "Проверьте: 1) YANDEX_VISION_API_KEY в .env 2) чёткость фото, освещение. "
                    "Команда /test — проверить парсинг."
                )
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
async def cmd_ocr_raw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ожидание фото для показа сырого OCR и результата парсинга (отладка)"""
    context.user_data["next_photo_ocr_debug"] = True
    await update.message.reply_text("📷 Отправьте фото паспорта — покажу сырой OCR и разбор.")


@admin_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка фото — сохраняем в контекст и ждём /готово или следующее фото"""
    if context.user_data.get("next_photo_ocr_debug"):
        context.user_data["next_photo_ocr_debug"] = False
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_path = os.path.join(tempfile.gettempdir(), f"ocr_debug_{photo.file_unique_id}.jpg")
        await file.download_to_drive(photo_path)
        try:
            from ocr_extractor import extract_text_from_image, parse_passport_data
            ocr = extract_text_from_image(photo_path)
            data = parse_passport_data(ocr or "")
            msg = f"📄 Сырой OCR ({len(ocr)} симв.):\n{(ocr or '(пусто)')[:1200]}\n\n"
            msg += "📋 Разбор:\n"
            for k, v in data.items():
                if v:
                    msg += f"{k}: {v}\n"
            await update.message.reply_text(msg[:4000])
        finally:
            try:
                os.unlink(photo_path)
            except Exception:
                pass
        return

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

    empty_count = sum(1 for r in results if not r.get("Фамилия") and not r.get("Серия и номер паспорта"))
    if empty_count == len(results) and results:
        await update.message.reply_text(
            "⚠️ OCR не распознал данные. Проверьте YANDEX_VISION_API_KEY и качество фото. /test — проверить парсинг."
        )

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
    app.add_handler(CommandHandler("test", cmd_test))
    app.add_handler(CommandHandler("diagnose", cmd_diagnose))
    app.add_handler(CommandHandler("ocr_raw", cmd_ocr_raw))
    app.add_handler(CommandHandler("ready", process_ready))
    app.add_handler(
        MessageHandler(filters.Document.ALL, handle_document)
    )
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Бот запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
