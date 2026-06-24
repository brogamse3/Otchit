import sqlite3
import hashlib
import os
from pathlib import Path
from collections import Counter

DATABASE_FILE = "file_registry.db"
CHUNK_SIZE = 4096

class FileIndexer:
    def __init__(self, db_path=DATABASE_FILE):
        self.db_path = db_path
        self.connection = None
        self._connect()
        self._setup_schema()

    def _connect(self):
        """Устанавливает соединение с БД."""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA journal_mode=WAL;")

    def _setup_schema(self):
        """Создает таблицу, если её нет. Структура немного изменена."""
        cursor = self.connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_records (
                file_path TEXT PRIMARY KEY,
                file_size BIGINT,
                last_modified REAL,
                content_hash TEXT
            )
        """)
        self.connection.commit()

    @staticmethod
    def compute_fingerprint(file_path: str) -> str | None:
        """Вычисляет MD5 хеш файла. Статический метод для независимости."""
        hasher = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                while True:
                    data = f.read(CHUNK_SIZE)
                    if not data:
                        break
                    hasher.update(data)
            return hasher.hexdigest()
        except (PermissionError, OSError):
            return None

    def update_index(self, target_dir: str):
        """Сканирует директорию и обновляет запись в БД."""
        print(f"[INFO] Индексация директории: {target_dir}")
        cursor = self.connection.cursor()
        processed_count = 0
        target_path = Path(target_dir).resolve()

        for current_root, _, filenames in os.walk(target_path):
            for fname in filenames:
                full_path = Path(current_root) / fname
                
                try:
                    stats = full_path.stat()
                    current_mtime = stats.st_mtime
                    current_size = stats.st_size
                    
                    cursor.execute(
                        "SELECT last_modified FROM file_records WHERE file_path=?", 
                        (str(full_path),)
                    )
                    record = cursor.fetchone()

                    if record and abs(record[0] - current_mtime) < 0.001:
                        continue

                    file_hash = self.compute_fingerprint(str(full_path))
                    
                    if file_hash:
                        cursor.execute(
                            """INSERT OR REPLACE INTO file_records 
                               (file_path, file_size, last_modified, content_hash) 
                               VALUES (?, ?, ?, ?)""",
                            (str(full_path), current_size, current_mtime, file_hash)
                        )
                        processed_count += 1
                        
                except Exception as err:
                    continue

        self.connection.commit()
        print(f"[DONE] Обработано новых/измененных файлов: {processed_count}")

    def detect_duplicates(self):
        """Ищет файлы с одинаковыми хешами."""
        print("[SEARCH] Поиск дубликатов...")
        cursor = self.connection.cursor()
        
        cursor.execute("""
            SELECT content_hash, GROUP_CONCAT(file_path, '|||') as paths_list
            FROM file_records
            WHERE content_hash IS NOT NULL
            GROUP BY content_hash
            HAVING COUNT(*) > 1
        """)
        
        duplicates_found = 0
        for row in cursor.fetchall():
            hash_val, paths_str = row
            paths = paths_str.split('|||')
            duplicates_found += 1
            
            print(f"\n--- Группа дубликатов #{duplicates_found} (Hash: {hash_val[:6]}...) ---")
            for p in paths:
                print(f"   -> {p}")

        if duplicates_found == 0:
            print("Результат: Дубликатов не обнаружено.")
        else:
            print(f"\nВсего найдено групп дубликатов: {duplicates_found}")

    def verify_backup_integrity(self, source_dir: str, backup_dir: str):
        """Сравнивает структуру и содержимое двух папок."""
        print(f"[CHECK] Сравнение: '{source_dir}' vs '{backup_dir}'")
        
        src_path = Path(source_dir).resolve()
        bak_path = Path(backup_dir).resolve()
        
        issues = []
        
        source_files = set()
        for root, _, files in os.walk(src_path):
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(src_path)
                source_files.add(rel)
                
                bak_full = bak_path / rel
                
                if not bak_full.exists():
                    issues.append(f"ОТСУТСТВУЕТ: {rel}")
                    continue
                
                if full.stat().st_size != bak_full.stat().st_size:
                    issues.append(f"РАЗМЕР НЕ СОВПАДАЕТ: {rel}")
                else:
                    pass

        if not issues:
            print("Статус: Бэкап идентичен оригиналу.")
        else:
            print(f"Найдено несоответствий: {len(issues)}")
            # Выводим первые 10 ошибок
            for issue in issues[:10]:
                print(f" ! {issue}")
            if len(issues) > 10:
                print(f" ... и еще {len(issues) - 10} ошибок скрыто.")

def run_interface():
    indexer = FileIndexer()
    
    menu_actions = {
        '1': "Индексация",
        '2': "Поиск дублей",
        '3': "Проверка бэкапа",
        '4': "Выход"
    }

    while True:
        print("\n" + "="*30)
        for key, val in menu_actions.items():
            print(f"{key}. {val}")
        print("="*30)
        
        user_input = input("Выберите действие: ").strip()

        if user_input == '1':
            dir_path = input("Путь для сканирования: ").strip()
            if Path(dir_path).is_dir():
                indexer.update_index(dir_path)
            else:
                print("Ошибка: Указанный путь не является директорией.")

        elif user_input == '2':
            indexer.detect_duplicates()

        elif user_input == '3':
            original = input("Путь к ОРИГИНАЛУ: ").strip()
            copy = input("Путь к КОПИИ: ").strip()
            
            if Path(original).is_dir() and Path(copy).is_dir():
                indexer.verify_backup_integrity(original, copy)
            else:
                print("Ошибка: Один из путей неверен.")

        elif user_input == '4':
            if indexer.connection:
                indexer.connection.close()
            print("Завершение работы.")
            break
        else:
            print("Некорректный ввод.")

if __name__ == "__main__":
    run_interface()