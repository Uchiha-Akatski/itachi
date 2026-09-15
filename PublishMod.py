# meta developer: @Wers1xx
# meta pic: https://img.icons8.com/color/48/000000/python.png
# meta banner: https://i.imgur.com/your_banner.jpg
# scope: hikka_only
# scope: hikka_min 1.2.10

import logging
import inspect
import importlib.util
import sys
import os
import re
import ast
import base64
import aiohttp
from typing import Union, Optional
from telethon.tl.types import Message
from telethon.tl.types import InputMediaWebPage

from .. import loader, utils

logger = logging.getLogger(__name__)


@loader.tds
class PublishMod(loader.Module):
    """Публикация модулей в канал + авто-загрузка в GitHub"""
    strings = {"name": "PublishMod"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "github_raw_link",
                "https://raw.githubusercontent.com/Wersixx/Wers1xx/main/",
                "Ссылка на raw GitHub (с / в конце)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "github_repo",
                "Wersixx/Wers1xx",
                "Репозиторий GitHub в формате owner/repo",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "github_token",
                "",
                "GitHub Personal Access Token (нужны права repo)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "github_branch",
                "main",
                "Ветка репозитория",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "auto_upload_github",
                True,
                "Автоматически загружать модуль в GitHub перед публикацией",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "channel",
                "@your_channel",
                "Канал для публикации (@username или -100... id)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "media_url",
                "https://x0.at/3Wu7.jpg",
                "Ссылка на медиа для публикации",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "quote_media",
                True,
                "Использовать quote_media",
                validator=loader.validators.Boolean(),
            ),
            loader.ConfigValue(
                "invert_media",
                True,
                "Использовать invert_media",
                validator=loader.validators.Boolean(),
            ),
        )

    async def pmcmd(self, message: Message):
        """<reply to module file> [описание обновления] - Опубликовать модуль в канал (+ GitHub)"""
        reply = await message.get_reply_message()
        
        if not reply or not reply.file:
            await utils.answer(message, "<emoji document_id=5121063440311386962>👎</emoji> <b>Ответь на файл модуля!</b>")
            return
        
        if not reply.file.name.endswith(".py"):
            await utils.answer(message, "<emoji document_id=5121063440311386962>👎</emoji> <b>Это не Python файл!</b>")
            return
        
        # Текст после команды = описание обновления (если есть)
        update_description = utils.get_args_raw(message).strip() or "Обновление модуля"
        
        await utils.answer(message, "<emoji document_id=5253464392850221514>🔃</emoji> <b>Анализирую модуль...</b>")
        
        # Скачиваем файл
        file_path = await reply.download_media()
        
        try:
            # Анализируем модуль
            module_info = self._analyze_module(file_path)
            
            if not module_info:
                await utils.answer(message, "<emoji document_id=5121063440311386962>👎</emoji> <b>Не удалось проанализировать модуль!</b>")
                return
            
            # Используем название модуля из strings["name"] для ссылки и имени файла
            module_name = module_info.get("name")
            if not module_name or module_name == "Unknown":
                await utils.answer(message, "<emoji document_id=5121063440311386962>👎</emoji> <b>Не удалось определить имя модуля (strings['name'])!</b>")
                return
            
            # Очищаем имя файла от недопустимых символов
            safe_name = re.sub(r'[^\w\-.]', '', module_name)
            if not safe_name:
                safe_name = "module"
            
            target_filename = f"{safe_name}.py"
            
            # Переименовываем файл локально
            dir_name = os.path.dirname(file_path) or "."
            new_file_path = os.path.join(dir_name, target_filename)
            
            if file_path != new_file_path:
                os.rename(file_path, new_file_path)
                file_path = new_file_path
            
            # === Авто-загрузка в GitHub ===
            file_existed = False  # по умолчанию считаем новым
            
            if self.config["auto_upload_github"]:
                await utils.answer(message, f"<emoji document_id=5253464392850221514>🔃</emoji> <b>Загружаю <code>{target_filename}</code> в GitHub...</b>")
                
                upload_result = await self._upload_to_github(file_path, target_filename)
                
                if not upload_result["success"]:
                    await utils.answer(
                        message,
                        f"<emoji document_id=5121063440311386962>👎</emoji> <b>Ошибка загрузки в GitHub:</b>\n<code>{upload_result['error']}</code>"
                    )
                    return
                
                file_existed = upload_result.get("existed", False)
                
                status_text = "обновлён" if file_existed else "загружен"
                await utils.answer(
                    message,
                    f"<emoji document_id=5123163417326126159>✅</emoji> <b>Модуль успешно {status_text} в GitHub!</b>\n"
                    f"<code>{upload_result.get('html_url', '')}</code>"
                )
                
                # Обновляем / создаём full.txt (только если модуль новый)
                if not file_existed:
                    full_result = await self._update_full_txt(safe_name)
                    if full_result.get("success"):
                        action = full_result.get("action", "обновлён")
                        await utils.answer(
                            message,
                            f"<emoji document_id=5123163417326126159>✅</emoji> <b>full.txt {action}</b>"
                        )
                    else:
                        logger.warning(f"full.txt update failed: {full_result.get('error')}")
            
            # Формируем сообщение для публикации
            if file_existed:
                text = self._format_update_message(module_name, update_description)
            else:
                text = self._format_message(module_info, module_name)
            
            # Получаем чат для публикации
            channel = self.config["channel"]
            try:
                entity = await message.client.get_entity(channel)
            except Exception:
                await utils.answer(message, f"<emoji document_id=5121063440311386962>👎</emoji> <b>Не удалось найти канал {channel}!</b>")
                return
            
            # Отправляем эмодзи в канал
            channel_message = await message.client.send_message(
                entity,
                '<emoji document_id=5116512467194741904>👾</emoji>'
            )
            
            # Подготавливаем медиа
            media_url = self.config["media_url"]
            banner = None
            
            if media_url and self.config["quote_media"]:
                banner = InputMediaWebPage(media_url, optional=True)
            elif media_url:
                banner = media_url
            
            # Редактируем сообщение в канале на полноценный пост
            try:
                await channel_message.edit(
                    text,
                    parse_mode="html",
                    file=banner,
                    invert_media=self.config["invert_media"],
                )
            except Exception as e:
                logger.error(f"Failed to edit with media: {e}")
                # Фолбек - редактируем без медиа
                await channel_message.edit(text, parse_mode="html")
            
            if file_existed:
                await utils.answer(message, "<emoji document_id=5123163417326126159>✅</emoji> <b>Обновление модуля успешно опубликовано в канал!</b>")
            else:
                await utils.answer(message, "<emoji document_id=5123163417326126159>✅</emoji> <b>Модуль успешно опубликован в канал!</b>")
            
        except Exception as e:
            logger.error(f"Error publishing module: {e}")
            await utils.answer(message, f"<emoji document_id=5121063440311386962>👎</emoji> <b>Ошибка:</b> {e}")
        finally:
            # Удаляем временный файл
            if os.path.exists(file_path):
                os.remove(file_path)

    async def _upload_to_github(self, file_path: str, filename: str) -> dict:
        """
        Загружает файл в GitHub через Contents API.
        Если файл уже существует — обновляет его.
        Возвращает existed=True, если файл уже был в репозитории.
        """
        token = self.config["github_token"].strip()
        repo = self.config["github_repo"].strip()
        branch = self.config["github_branch"].strip() or "main"
        
        if not token:
            return {"success": False, "error": "Не указан github_token в конфиге!"}
        
        if not repo or "/" not in repo:
            return {"success": False, "error": "Неверный формат github_repo (нужно owner/repo)"}
        
        # Читаем содержимое файла
        try:
            with open(file_path, "rb") as f:
                content_bytes = f.read()
            content_b64 = base64.b64encode(content_bytes).decode("utf-8")
        except Exception as e:
            return {"success": False, "error": f"Не удалось прочитать файл: {e}"}
        
        api_base = f"https://api.github.com/repos/{repo}/contents/{filename}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Hikka-PublishMod",
        }
        
        async with aiohttp.ClientSession() as session:
            # Сначала проверяем, существует ли файл (чтобы получить sha для обновления)
            sha = None
            existed = False
            try:
                async with session.get(
                    api_base,
                    headers=headers,
                    params={"ref": branch},
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        sha = data.get("sha")
                        existed = True
                    elif resp.status == 404:
                        sha = None  # файла нет — будем создавать
                        existed = False
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Ошибка проверки файла ({resp.status}): {text[:200]}"}
            except Exception as e:
                return {"success": False, "error": f"Ошибка сети при проверке: {e}"}
            
            # Формируем тело запроса
            payload = {
                "message": f"Upload module: {filename}",
                "content": content_b64,
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha  # обновление существующего файла
                payload["message"] = f"Update module: {filename}"
            
            try:
                async with session.put(
                    api_base,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    result = await resp.json()
                    
                    if resp.status in (200, 201):
                        html_url = result.get("content", {}).get("html_url") or result.get("commit", {}).get("html_url", "")
                        return {
                            "success": True,
                            "html_url": html_url,
                            "sha": result.get("content", {}).get("sha"),
                            "existed": existed,
                        }
                    else:
                        error_msg = result.get("message", str(result))
                        return {"success": False, "error": f"GitHub API ({resp.status}): {error_msg}"}
            except Exception as e:
                return {"success": False, "error": f"Ошибка загрузки: {e}"}

    async def _update_full_txt(self, module_name: str) -> dict:
        """
        Обновляет/создаёт full.txt в корне репозитория.
        - Если файла нет → создаёт и записывает все .py модули, которые сейчас есть в репо.
        - Если файл есть → добавляет название нового модуля (если его ещё нет).
        """
        token = self.config["github_token"].strip()
        repo = self.config["github_repo"].strip()
        branch = self.config["github_branch"].strip() or "main"
        
        if not token or not repo or "/" not in repo:
            return {"success": False, "error": "Не настроен github_token / github_repo"}
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "Hikka-PublishMod",
        }
        
        full_txt_path = "full.txt"
        api_file = f"https://api.github.com/repos/{repo}/contents/{full_txt_path}"
        
        async with aiohttp.ClientSession() as session:
            # 1. Проверяем, существует ли full.txt
            sha = None
            current_content = ""
            file_exists = False
            
            try:
                async with session.get(
                    api_file,
                    headers=headers,
                    params={"ref": branch},
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        sha = data.get("sha")
                        file_exists = True
                        # Декодируем содержимое
                        content_b64 = data.get("content", "")
                        if content_b64:
                            current_content = base64.b64decode(content_b64).decode("utf-8")
                    elif resp.status == 404:
                        file_exists = False
                    else:
                        text = await resp.text()
                        return {"success": False, "error": f"Ошибка чтения full.txt ({resp.status}): {text[:200]}"}
            except Exception as e:
                return {"success": False, "error": f"Ошибка сети при чтении full.txt: {e}"}
            
            # 2. Формируем новое содержимое
            if not file_exists:
                # Создаём full.txt — собираем все .py файлы из корня репозитория
                modules = await self._list_repo_py_modules(session, headers, repo, branch)
                # Добавляем текущий модуль на всякий случай
                if module_name not in modules:
                    modules.append(module_name)
                modules = sorted(set(modules), key=str.lower)
                new_content = "\n".join(modules) + "\n"
                commit_msg = "Create full.txt with all modules"
                action = "создан"
            else:
                # Файл есть — добавляем новый модуль, если его ещё нет
                lines = [line.strip() for line in current_content.splitlines() if line.strip()]
                if module_name in lines:
                    # Уже есть — ничего не делаем
                    return {"success": True, "action": "уже содержит модуль (без изменений)"}
                
                lines.append(module_name)
                lines = sorted(set(lines), key=str.lower)
                new_content = "\n".join(lines) + "\n"
                commit_msg = f"Add {module_name} to full.txt"
                action = "обновлён"
            
            # 3. Записываем файл
            content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
            payload = {
                "message": commit_msg,
                "content": content_b64,
                "branch": branch,
            }
            if sha:
                payload["sha"] = sha
            
            try:
                async with session.put(
                    api_file,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status in (200, 201):
                        return {"success": True, "action": action}
                    else:
                        result = await resp.json()
                        error_msg = result.get("message", str(result))
                        return {"success": False, "error": f"GitHub API ({resp.status}): {error_msg}"}
            except Exception as e:
                return {"success": False, "error": f"Ошибка записи full.txt: {e}"}

    async def _list_repo_py_modules(self, session, headers: dict, repo: str, branch: str) -> list:
        """Получает список названий .py модулей (без расширения) из корня репозитория"""
        modules = []
        api_url = f"https://api.github.com/repos/{repo}/contents/"
        
        try:
            async with session.get(
                api_url,
                headers=headers,
                params={"ref": branch},
                timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                if resp.status != 200:
                    return modules
                
                items = await resp.json()
                if not isinstance(items, list):
                    return modules
                
                for item in items:
                    if item.get("type") == "file":
                        name = item.get("name", "")
                        if name.endswith(".py") and name != "full.txt":
                            # Убираем .py
                            modules.append(name[:-3])
        except Exception as e:
            logger.warning(f"Failed to list repo modules: {e}")
        
        return modules

    def _analyze_module(self, file_path: str) -> dict:
        """Анализирует Python файл модуля"""
        info = {
            "name": None,
            "description": None,
            "commands": [],
            "meta_developer": None,
        }
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # Ищем meta developer (поддерживает несколько разработчиков)
            meta_dev_match = re.search(r'#\s*meta\s+developer:\s*(.+)', content, re.IGNORECASE)
            if meta_dev_match:
                raw_devs = meta_dev_match.group(1).strip()
                # Извлекаем все @username
                usernames = re.findall(r'@([\w]+)', raw_devs)
                if usernames:
                    info["meta_developer"] = ", ".join(f"@{u}" for u in usernames)
                else:
                    # Если @ не найдены — берём как есть
                    info["meta_developer"] = raw_devs
            
            # Ищем класс модуля
            class_match = re.search(r'class\s+(\w+)\(loader\.Module\):', content)
            module_class_name = class_match.group(1) if class_match else None
            
            # Извлекаем описание модуля из docstring класса через regex
            if module_class_name:
                class_doc_pattern = rf'class\s+{module_class_name}\(loader\.Module\):\s*\n\s*"""(.*?)"""'
                class_doc_match = re.search(class_doc_pattern, content, re.DOTALL)
                if class_doc_match:
                    doc_text = class_doc_match.group(1).strip()
                    # Берем первую строку как описание
                    first_line = doc_text.split('\n')[0].strip()
                    if first_line:
                        info["description"] = first_line
                else:
                    # Пробуем найти любой docstring класса
                    doc_match = re.search(r'class\s+\w+\(loader\.Module\):\s*\n\s*"""(.*?)"""', content, re.DOTALL)
                    if doc_match:
                        doc_text = doc_match.group(1).strip()
                        first_line = doc_text.split('\n')[0].strip()
                        if first_line:
                            info["description"] = first_line
            
            # Извлекаем команды через комбинированный подход
            info["commands"] = self._extract_all_commands(content)
            
            # Пытаемся загрузить модуль для получения названия
            if module_class_name:
                try:
                    spec = importlib.util.spec_from_file_location(
                        module_class_name, file_path
                    )
                    module = importlib.util.module_from_spec(spec)
                    
                    sys.modules[module_class_name] = module
                    spec.loader.exec_module(module)
                    
                    # Ищем класс модуля для получения имени
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if hasattr(obj, 'strings') and 'name' in obj.strings:
                            info["name"] = str(obj.strings["name"])
                            break
                    
                    # Удаляем загруженный модуль
                    if module_class_name in sys.modules:
                        del sys.modules[module_class_name]
                    
                except Exception as e:
                    logger.warning(f"Failed to dynamically load module: {e}")
            
            # Если имя не найдено, пытаемся найти через regex
            if not info["name"]:
                name_match = re.search(r'"name":\s*"([^"]+)"', content)
                if not name_match:
                    name_match = re.search(r"'name':\s*'([^']+)'", content)
                if name_match:
                    info["name"] = name_match.group(1)
                else:
                    info["name"] = module_class_name or "Unknown"
            
            # Удаляем дубликаты команд
            seen = set()
            unique_commands = []
            for cmd in info["commands"]:
                if cmd["name"] not in seen:
                    seen.add(cmd["name"])
                    unique_commands.append(cmd)
            info["commands"] = unique_commands
            
        except Exception as e:
            logger.error(f"Error analyzing module: {e}")
            return None
        
        return info

    def _extract_all_commands(self, content: str) -> list:
        """Извлекает все команды используя комбинацию методов"""
        commands = []
        seen = set()
        
        # Метод 1: AST парсинг (самый надежный)
        ast_commands = self._extract_commands_ast_enhanced(content)
        for cmd in ast_commands:
            if cmd["name"] not in seen:
                seen.add(cmd["name"])
                commands.append(cmd)
        
        # Метод 2: Улучшенный regex для @loader.command()
        regex_commands = self._extract_commands_regex_advanced(content)
        for cmd in regex_commands:
            if cmd["name"] not in seen:
                seen.add(cmd["name"])
                commands.append(cmd)
        
        # Метод 3: Старый стиль (методы с cmd)
        old_commands = self._extract_commands_old_style(content)
        for cmd in old_commands:
            if cmd["name"] not in seen:
                seen.add(cmd["name"])
                commands.append(cmd)
        
        return commands

    def _extract_commands_ast_enhanced(self, content: str) -> list:
        """Улучшенный AST парсинг команд"""
        commands = []
        try:
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
                
                # Проверяем декораторы
                for decorator in node.decorator_list:
                    is_command = False
                    description = ""
                    
                    # Случай: @loader.command(...)
                    if isinstance(decorator, ast.Call):
                        # Проверяем что это вызов loader.command или command
                        if isinstance(decorator.func, ast.Attribute):
                            if (decorator.func.attr == 'command' and 
                                isinstance(decorator.func.value, ast.Name) and 
                                decorator.func.value.id == 'loader'):
                                is_command = True
                                description = self._extract_description_from_ast_call(decorator)
                        elif isinstance(decorator.func, ast.Name) and decorator.func.id == 'command':
                            is_command = True
                            description = self._extract_description_from_ast_call(decorator)
                    
                    # Случай: @loader.command (без скобок)
                    elif isinstance(decorator, ast.Attribute):
                        if (decorator.attr == 'command' and 
                            isinstance(decorator.value, ast.Name) and 
                            decorator.value.id == 'loader'):
                            is_command = True
                    
                    # Случай: @command (без скобок)
                    elif isinstance(decorator, ast.Name) and decorator.id == 'command':
                        is_command = True
                    
                    if is_command:
                        cmd_name = node.name
                        # Убираем суффиксы
                        if cmd_name.endswith('cmd'):
                            cmd_name = cmd_name[:-3]
                        elif cmd_name.endswith('_cmd'):
                            cmd_name = cmd_name[:-4]
                        cmd_name = cmd_name.replace('_', '')
                        
                        # Если описание не найдено, берем из докстринга
                        if not description:
                            if node.body and isinstance(node.body[0], ast.Expr):
                                if isinstance(node.body[0].value, ast.Constant):
                                    doc = node.body[0].value.value
                                    if isinstance(doc, str):
                                        doc = doc.strip()
                                        if doc:
                                            first_line = doc.split('\n')[0].strip()
                                            description = first_line[:100]
                        
                        if cmd_name and not any(c["name"] == cmd_name for c in commands):
                            commands.append({
                                "name": cmd_name,
                                "description": description
                            })
                        break
                        
        except Exception as e:
            logger.warning(f"AST enhanced parsing error: {e}")
        
        return commands

    def _extract_description_from_ast_call(self, call_node) -> str:
        """Извлекает описание из AST Call узла"""
        try:
            # Проверяем ключевые аргументы
            ru_doc = None
            en_doc = None
            ua_doc = None
            
            for keyword in call_node.keywords:
                if keyword.arg == 'ru_doc':
                    if isinstance(keyword.value, ast.Constant):
                        ru_doc = keyword.value.value
                elif keyword.arg == 'en_doc':
                    if isinstance(keyword.value, ast.Constant):
                        en_doc = keyword.value.value
                elif keyword.arg == 'ua_doc':
                    if isinstance(keyword.value, ast.Constant):
                        ua_doc = keyword.value.value
            
            # Приоритет: ru_doc > en_doc > ua_doc
            if ru_doc and isinstance(ru_doc, str):
                return ru_doc[:100]
            elif en_doc and isinstance(en_doc, str):
                return en_doc[:100]
            elif ua_doc and isinstance(ua_doc, str):
                return ua_doc[:100]
            
            # Проверяем позиционные аргументы
            for arg in call_node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return arg.value[:100]
                    
        except Exception:
            pass
        
        return ""

    def _extract_commands_regex_advanced(self, content: str) -> list:
        """Улучшенный regex парсинг для @loader.command()"""
        commands = []
        seen = set()
        
        # Находим все @loader.command() декораторы с их аргументами
        pattern = r'@loader\.command\s*\(\s*(.*?)\s*\)\s*\n\s*async\s+def\s+(\w+)\s*\([^)]*\):'
        
        for match in re.finditer(pattern, content, re.DOTALL):
            args_str = match.group(1)
            cmd_name = match.group(2)
            
            # Убираем суффиксы
            if cmd_name.endswith('cmd'):
                cmd_name = cmd_name[:-3]
            elif cmd_name.endswith('_cmd'):
                cmd_name = cmd_name[:-4]
            cmd_name = cmd_name.replace('_', '')
            
            if cmd_name and cmd_name not in seen:
                seen.add(cmd_name)
                description = self._extract_description_from_args_string(args_str)
                commands.append({"name": cmd_name, "description": description})
        
        # Ищем @loader.command без аргументов
        pattern_no_args = r'@loader\.command\s*\n\s*async\s+def\s+(\w+)\s*\([^)]*\):'
        for match in re.finditer(pattern_no_args, content):
            cmd_name = match.group(1)
            if cmd_name.endswith('cmd'):
                cmd_name = cmd_name[:-3]
            elif cmd_name.endswith('_cmd'):
                cmd_name = cmd_name[:-4]
            cmd_name = cmd_name.replace('_', '')
            
            if cmd_name and cmd_name not in seen:
                seen.add(cmd_name)
                # Ищем докстринг
                desc = self._extract_docstring_for_function(content, match.group(1))
                commands.append({"name": cmd_name, "description": desc})
        
        return commands

    def _extract_description_from_args_string(self, args_str: str) -> str:
        """Извлекает описание из строки аргументов декоратора"""
        # Ищем ru_doc
        ru_match = re.search(r'ru_doc\s*=\s*["\']([^"\']*)["\']', args_str, re.DOTALL)
        if ru_match:
            desc = ru_match.group(1).strip()
            desc = re.sub(r'\s+', ' ', desc)
            return desc[:100]
        
        # Ищем en_doc
        en_match = re.search(r'en_doc\s*=\s*["\']([^"\']*)["\']', args_str, re.DOTALL)
        if en_match:
            desc = en_match.group(1).strip()
            desc = re.sub(r'\s+', ' ', desc)
            return desc[:100]
        
        # Ищем ua_doc
        ua_match = re.search(r'ua_doc\s*=\s*["\']([^"\']*)["\']', args_str, re.DOTALL)
        if ua_match:
            desc = ua_match.group(1).strip()
            desc = re.sub(r'\s+', ' ', desc)
            return desc[:100]
        
        # Ищем doc
        doc_match = re.search(r'doc\s*=\s*["\']([^"\']*)["\']', args_str, re.DOTALL)
        if doc_match:
            desc = doc_match.group(1).strip()
            desc = re.sub(r'\s+', ' ', desc)
            return desc[:100]
        
        return ""

    def _extract_docstring_for_function(self, content: str, func_name: str) -> str:
        """Извлекает докстринг для указанной функции"""
        pattern = rf'async\s+def\s+{func_name}\s*\([^)]*\):\s*\n\s*"""([^"]*)"""'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            doc = match.group(1).strip()
            first_line = doc.split('\n')[0].strip()
            return first_line[:100]
        return ""

    def _extract_commands_old_style(self, content: str) -> list:
        """Извлекает команды старого стиля (методы с cmd)"""
        commands = []
        seen = set()
        
        # Ищем методы с cmd в названии
        pattern = r'async\s+def\s+(\w+cmd)\s*\([^)]*\):'
        for match in re.finditer(pattern, content):
            cmd_func_name = match.group(1)
            cmd_name = cmd_func_name.replace('cmd', '').replace('_', '')
            
            if cmd_name and cmd_name not in seen:
                seen.add(cmd_name)
                # Ищем докстринг
                desc = self._extract_docstring_for_function(content, cmd_func_name)
                commands.append({"name": cmd_name, "description": desc})
        
        return commands

    def _format_update_message(self, module_name: str, update_description: str) -> str:
        """Форматирует сообщение об обновлении модуля"""
        github_link = self.config["github_raw_link"].rstrip('/') + '/' + module_name + '.py'
        clean_name = module_name or "Без названия"
        
        # Ограничиваем длину описания обновления
        if len(update_description) > 500:
            update_description = update_description[:497] + "..."
        
        text = (
            '<blockquote>'
            f'<emoji document_id=5253952855185829086>⚙️</emoji> Обновление модуля <b>{clean_name}</b>'
            '</blockquote>\n'
            '<blockquote>'
            f'{update_description}'
            '</blockquote>\n'
            '<blockquote>'
            f'<emoji document_id=5253577054137362120>🔗</emoji> Ссылка для обновления:\n'
            f'<code>dlm {github_link}</code>'
            '</blockquote>'
        )
        
        return text

    def _format_message(self, module_info: dict, module_name: str) -> str:
        """Форматирует сообщение для публикации нового модуля"""
        github_link = self.config["github_raw_link"].rstrip('/') + '/' + module_name + '.py'
        
        # Очищаем имя модуля
        clean_name = module_name or "Без названия"
        
        # Получаем описание модуля
        module_desc = module_info.get("description") or "Без описания"
        if len(module_desc) > 200:
            module_desc = module_desc[:197] + "..."
        
        text = (
            '<blockquote expandable>'
            f'<emoji document_id=5253521692008917018>🌙</emoji> Модуль <b>{clean_name}</b>.\n'
            f'<emoji document_id=5256230583717079814>📝</emoji> {module_desc}'
            '</blockquote>\n\n'
        )
        
        if module_info["commands"]:
            max_commands = 5
            total_commands = len(module_info["commands"])
            
            # Сортируем команды
            sorted_commands = sorted(module_info["commands"], key=lambda x: x["name"])
            
            for cmd in sorted_commands[:max_commands]:
                desc = cmd["description"] or "Без описания"
                text += (
                    '<blockquote expandable>'
                    f'<emoji document_id=5197195523794157505>▫️</emoji> <code>.{cmd["name"]}</code> '
                    f'{desc}'
                    '</blockquote>\n'
                )
            
            if total_commands > max_commands:
                text += (
                    '\n<blockquote>'
                    f'<emoji document_id=6021435576513730578>📋</emoji> <b>И ещё {total_commands - max_commands} команд.</b>\n'
                    '<i>Остальное увидите когда скачаете модуль.</i>'
                    '</blockquote>\n'
                )
            
            text += '\n'
        else:
            text += (
                '<blockquote expandable>'
                '<emoji document_id=6021435576513730578>📋</emoji> <b>Команды не обнаружены</b>\n'
                '<i>Возможно модуль использует другой способ регистрации</i>'
                '</blockquote>\n\n'
            )
        
        # Добавляем информацию о разработчике(ах)
        if module_info.get("meta_developer"):
            devs = module_info["meta_developer"]
            # Если несколько — пишем "Разработчики"
            label = "Разработчики" if "," in devs else "Разработчик"
            text += (
                '<blockquote expandable>'
                f'<emoji document_id=5253464392850221514>👨‍💻</emoji> <b>{label}:</b> {devs}'
                '</blockquote>\n\n'
            )
        
        text += (
            '<blockquote expandable>'
            f'<emoji document_id=5256094480498436162>📦</emoji> Ссылка:\n'
            f'<code>dlm {github_link}</code>'
            '</blockquote>'
        )
        
        return text

    async def client_ready(self, client, db):
        self.client = client
