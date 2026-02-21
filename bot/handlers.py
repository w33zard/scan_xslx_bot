# -*- coding: utf-8 -*-
"""
Обработчики Telegram: document, photo, JSON output
"""
import asyncio
import io
import json
import logging
import shutil
import zipfile
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.config import ADMIN_IDS, MAX_FILE_MB
from bot.utils_files import safe_temp_path, cleanup_path

logger = logging.getLogger(__name__)


def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if ADMIN_IDS and user_id not in ADMIN_IDS:
            await update.message.reply_text("⛔ Доступ запрещён.")
            return
        return await func(update, context)
    return wrapper


def _format_result_summary(result: dict) -> str:
    """Краткое человекочитаемое резюме полей"""
    fields = result.get("fields", {})
    parts = []
    for key, fv in fields.items():
        if isinstance(fv, dict):
            v = fv.get("value")
        else:
            v = getattr(fv, "value", None)
        if v:
            label = {
                "surname": "Фамилия",
                "name": "Имя",
                "patronymic": "Отчество",
                "gender": "Пол",
                "birth_date": "Дата рождения",
                "birth_place": "Место рождения",
                "passport_series": "Серия",
                "passport_number": "Номер",
                "issue_date": "Дата выдачи",
                "issue_place": "Кем выдан",
                "authority_code": "Код подразделения",
                "registration_address": "Адрес",
            }.get(key, key)
            parts.append(f"{label}: {v}")
    if result.get("errors"):
        parts.append("⚠️ " + "; ".join(result["errors"][:3]))
    return "\n".join(parts) if parts else "Данные не извлечены"


@admin_only
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка документа (ZIP или изображение)"""
    doc = update.message.document
    if not doc:
        return

    fname = (doc.file_name or "").lower()
    if fname.endswith(".zip"):
        await _handle_zip(update, context, doc)
        return

    if fname.endswith((".jpg", ".jpeg", ".png", ".pdf")):
        await _handle_single_file(update, context, doc)
        return

    await update.message.reply_text(
        "⚠️ Поддерживаются: ZIP, JPG, PNG, PDF. Отправьте изображение или архив."
    )


async def _handle_single_file(update: Update, context: ContextTypes.DEFAULT_TYPE, doc) -> None:
    """Обработка одного файла (фото/PDF)"""
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await update.message.reply_text(
            f"⚠️ Файл слишком большой (макс {MAX_FILE_MB} MB). Сожмите изображение."
        )
        return

    await update.message.reply_text("📥 Получаю файл...")

    path = None
    orig_path = None
    pdf_pages = []
    try:
        file = await context.bot.get_file(doc.file_id)
        suffix = Path(doc.file_name or "file").suffix or ".jpg"
        orig_path = safe_temp_path(prefix="doc", suffix=suffix)
        await file.download_to_drive(orig_path)
        path = orig_path

        if suffix.lower() == ".pdf":
            try:
                import pdf2image
                pages = pdf2image.convert_from_path(orig_path, dpi=150)
                folder = Path(orig_path).parent / f"pdf_{id(orig_path)}"
                folder.mkdir(exist_ok=True)
                for i, p in enumerate(pages):
                    p_path = folder / f"page_{i}.png"
                    p.save(str(p_path))
                    pdf_pages.append(str(p_path))
            except ImportError:
                await update.message.reply_text("❌ PDF не поддерживается. Установите pdf2image и poppler.")
                return
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка PDF: {e}")
                return

        await update.message.reply_text("🔍 Обрабатываю...")

        from ocr_extractor import process_passport_image, process_images_from_folder
        if pdf_pages:
            results = process_images_from_folder(str(folder))
            row = results[0] if results else {}
            try:
                shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                pass
        else:
            row = process_passport_image(path, index=1)
        summary = "\n".join(f"{k}: {v}" for k, v in row.items() if v and k != "№ п/п")

        await update.message.reply_text(f"📋 Результат:\n\n{summary[:3000]}")

        bio = io.BytesIO(json.dumps(row, ensure_ascii=False, indent=2).encode("utf-8"))
        bio.name = "passport_result.json"
        await update.message.reply_document(document=bio, filename="passport_result.json")

    except asyncio.TimeoutError:
        await update.message.reply_text("⏱ Превышено время обработки. Попробуйте меньшее изображение.")
    except Exception as e:
        logger.exception("Document handling error")
        await update.message.reply_text(f"❌ Ошибка: {type(e).__name__}")
    finally:
        cleanup_path(orig_path or "")


async def _handle_zip(update: Update, context: ContextTypes.DEFAULT_TYPE, doc) -> None:
    """Обработка ZIP-архива (множество паспортов → Excel + JSON)"""
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await update.message.reply_text(
            f"⚠️ Архив слишком большой (макс {MAX_FILE_MB} MB)."
        )
        return

    await update.message.reply_text("📥 Получаю архив...")

    zip_path = None
    extract_dir = None
    try:
        file = await context.bot.get_file(doc.file_id)
        zip_path = safe_temp_path(prefix="zip", suffix=".zip")
        await file.download_to_drive(zip_path)

        extract_dir = Path(zip_path).with_suffix("")
        extract_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        await update.message.reply_text("🔍 Обрабатываю изображения...")

        from excel_export import normalize_results
        from ocr_extractor import process_images_from_folder
        results = process_images_from_folder(str(extract_dir))
        results = normalize_results(results)

        if not results:
            await update.message.reply_text("❌ В архиве не найдено изображений.")
            return

        from excel_export import create_excel

        out_excel = safe_temp_path(prefix="passports", suffix=".xlsx")
        create_excel(results, out_excel)

        json_bytes = json.dumps(results, ensure_ascii=False, indent=2).encode("utf-8")

        await update.message.reply_text(f"✅ Обработано: {len(results)}")
        await update.message.reply_document(document=open(out_excel, "rb"), filename="passports_data.xlsx")
        bio = io.BytesIO(json_bytes)
        bio.name = "passports_result.json"
        await update.message.reply_document(document=bio, filename="passports_result.json")

        cleanup_path(out_excel)

    except zipfile.BadZipFile:
        await update.message.reply_text("❌ Повреждённый ZIP-архив.")
    except Exception as e:
        logger.exception("ZIP handling error")
        await update.message.reply_text(f"❌ Ошибка: {type(e).__name__}")
    finally:
        cleanup_path(zip_path or "")
        if extract_dir and Path(extract_dir).exists():
            shutil.rmtree(extract_dir, ignore_errors=True)


def _fv(field) -> str:
    if field is None:
        return ""
    if isinstance(field, dict):
        return (field.get("value") or "") or ""
    return (getattr(field, "value", None) or "") or ""


@admin_only
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка фото паспорта (одиночное — сразу, или накопление для /ready)"""
    if context.user_data.get("next_photo_ocr_debug"):
        context.user_data["next_photo_ocr_debug"] = False
        await _handle_ocr_debug_photo(update, context)
        return

    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        return

    if photo.file_size and photo.file_size > MAX_FILE_MB * 1024 * 1024:
        await update.message.reply_text(f"⚠️ Файл слишком большой (макс {MAX_FILE_MB} MB).")
        return

    await update.message.reply_text("📥 Получаю фото...")
    path = None
    try:
        file = await context.bot.get_file(photo.file_id)
        path = safe_temp_path(prefix="photo", suffix=".jpg")
        await file.download_to_drive(path)
        if "pending_photos" not in context.user_data:
            context.user_data["pending_photos"] = []
        context.user_data["pending_photos"].append(path)
        count = len(context.user_data["pending_photos"])
        await update.message.reply_text(
            f"📷 Фото {count}. Отправьте ещё или /ready для обработки."
        )
    except Exception as e:
        logger.exception("Photo save error")
        cleanup_path(path or "")
        await update.message.reply_text(f"❌ Ошибка: {type(e).__name__}")


@admin_only
async def cmd_diagnose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Диагностика: Yandex, Tesseract, OCR"""
    import os
    import tempfile
    lines = []
    key = os.environ.get("YANDEX_VISION_API_KEY", "")
    lines.append(f"1. Yandex API: {'✅ ключ есть' if key else '❌ ключ НЕ задан'}")
    try:
        import pytesseract
        v = pytesseract.get_tesseract_version()
        lines.append(f"2. Tesseract: ✅ {v}")
    except Exception as e:
        lines.append(f"2. Tesseract: ❌ {e}")
    try:
        from PIL import Image, ImageDraw, ImageFont
        img = Image.new("RGB", (800, 300), "white")
        draw = ImageDraw.Draw(img)
        font = None
        for fp in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"]:
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
        lines.append(f"3. OCR: {len(ocr)} симв.")
        if ocr:
            lines.append(f"   Текст: {ocr[:120]}...")
        else:
            lines.append("   ❌ OCR пустой")
        data = parse_passport_data(ocr or "")
        lines.append(f"4. Парсинг: ФИО={bool(data.get('Фамилия'))}, Серия={data.get('Серия и номер паспорта') or 'пусто'}")
        try:
            os.unlink(path)
        except Exception:
            pass
    except Exception as e:
        lines.append(f"3-4. Ошибка: {e}")
    await update.message.reply_text("🔍 Диагностика:\n\n" + "\n".join(lines))


@admin_only
async def cmd_ocr_raw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Включить режим отладки OCR для следующего фото"""
    context.user_data["next_photo_ocr_debug"] = True
    await update.message.reply_text("📷 Отправьте фото — покажу сырой OCR и разбор.")


@admin_only
async def process_ready(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработать накопленные фото по /ready. Несколько фото = один паспорт (разворот + прописка)."""
    photos = context.user_data.get("pending_photos", [])
    if not photos:
        await update.message.reply_text("📷 Сначала отправьте фото паспортов, затем /ready")
        return

    await update.message.reply_text("🔍 Обрабатываю...")

    try:
        import tempfile
        folder = tempfile.mkdtemp()
        for i, p in enumerate(photos):
            dst = Path(folder) / f"page_{i}.jpg"
            if Path(p).exists():
                shutil.copy(p, dst)
        from excel_export import normalize_results
        from ocr_extractor import process_images_from_folder
        results = process_images_from_folder(folder)
        results = normalize_results(results)
        shutil.rmtree(folder, ignore_errors=True)
    except Exception as e:
        logger.exception("process_ready error")
        results = []
        try:
            shutil.rmtree(folder, ignore_errors=True)
        except Exception:
            pass

    for p in photos:
        cleanup_path(p)
    context.user_data["pending_photos"] = []

    if not results:
        await update.message.reply_text("❌ Не удалось обработать изображения.")
        return

    if len(results) == 1:
        row = results[0]
        summary = "\n".join(f"{k}: {v}" for k, v in row.items() if v and k != "№ п/п")
        await update.message.reply_text(f"📋 Результат:\n\n{summary[:3000]}")
        bio = io.BytesIO(json.dumps(row, ensure_ascii=False, indent=2).encode("utf-8"))
        bio.name = "passport_result.json"
        await update.message.reply_document(document=bio, filename="passport_result.json")

    out = safe_temp_path(prefix="passports", suffix=".xlsx")
    from excel_export import create_excel
    create_excel(results, out)
    await update.message.reply_text(f"✅ Обработано: {len(results)}")
    await update.message.reply_document(document=open(out, "rb"), filename="passports_data.xlsx")
    cleanup_path(out)


async def _handle_ocr_debug_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отладочный режим: сырой OCR + разбор"""
    photo = update.message.photo[-1]
    path = None
    try:
        file = await context.bot.get_file(photo.file_id)
        path = safe_temp_path(prefix="ocr_debug", suffix=".jpg")
        await file.download_to_drive(path)

        from passport_ocr.ocr_engines import get_engine
        from passport_ocr.ingest import get_image_array
        from passport_ocr.parse import parse_ocr_to_fields

        img = get_image_array(path)
        engine = get_engine()
        ocr_result = engine.recognize(img)
        ocr_text = ocr_result.text or ""
        fields = parse_ocr_to_fields(ocr_text)

        msg = f"📄 OCR ({len(ocr_text)} симв.):\n{(ocr_text or '(пусто)')[:800]}...\n\n📋 Поля:\n"
        for k, v in fields.items():
            val = getattr(v, "value", None) if hasattr(v, "value") else v.get("value") if isinstance(v, dict) else None
            if val:
                msg += f"{k}: {val}\n"
        await update.message.reply_text(msg[:4000])
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")
    finally:
        cleanup_path(path or "")
