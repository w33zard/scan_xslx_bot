"""
Telegram-бот для извлечения данных из сканов паспортов
Отправьте ZIP или папку с изображениями паспортов — бот вернёт Excel
"""
import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
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
        img = Image.new("RGB", (800, 300), "white")
        draw = ImageDraw.Draw(img)
        font = None
        for fp in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/TTF/DejaVuSans.ttf",
            "C:/Windows/Fonts/arial.ttf",
        ]:
            if os.path.isfile(fp):
                try:
                    font = ImageFont.truetype(fp, 36)
                    break
                except Exception:
                    pass
        if font:
            draw.text((30, 80), "ЦИЦАР ФЕДОР МИХАЙЛОВИЧ", fill="black", font=font)
            draw.text((30, 140), "4008 595794", fill="black", font=font)
        else:
            draw.text((30, 80), "ЦИЦАР ФЕДОР 4008 595794", fill="black")
        path = os.path.join(tempfile.gettempdir(), "diag_test.jpg")
        img.save(path, "JPEG", quality=95)

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
    """Обработка ZIP — делегируем в bot.handlers для единой логики"""
    from bot.handlers import handle_document as _hd
    await _hd(update, context)


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
    """Обработка накопленных фото: несколько фото = один паспорт (разворот + прописка), объединённый OCR."""
    photos = context.user_data.get("pending_photos", [])
    if not photos:
        await update.message.reply_text(
            "📷 Сначала отправьте фото паспортов, затем /ready"
        )
        return

    await update.message.reply_text("🔍 Обрабатываю изображения (OCR)...")

    folder = tempfile.mkdtemp()
    try:
        for i, p in enumerate(photos):
            dst = Path(folder) / f"page_{i}{Path(p).suffix or '.jpg'}"
            if Path(p).exists():
                shutil.copy(p, dst)
        results = process_images_from_folder(folder)
    except Exception as e:
        results = []
        import logging
        logging.getLogger(__name__).exception("process_ready error")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        for p in photos:
            try:
                os.unlink(p)
            except Exception:
                pass

    context.user_data["pending_photos"] = []

    if not results:
        await update.message.reply_text("❌ Не удалось обработать изображения.")
        return

    empty_count = sum(1 for r in results if not r.get("Фамилия") and not r.get("Серия и номер паспорта"))
    if empty_count == len(results) and results:
        await update.message.reply_text(
            "⚠️ OCR не распознал данные. Попробуйте /diagnose или пришлите лучшее качество фото."
        )

    output_path = os.path.join(tempfile.gettempdir(), "passports_data.xlsx")
    template = os.environ.get("TEMPLATE_EXCEL")
    create_excel(results, output_path, template_excel=template)

    await update.message.reply_text(f"✅ Обработано: {len(results)}")
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
