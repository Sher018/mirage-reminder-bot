"""Запускатель: перехватывает ошибки при импорте и запуске."""
import sys

def main():
    try:
        import main as bot_main
        bot_main.main()
    except KeyboardInterrupt:
        print("\nБот остановлен (Ctrl+C).", flush=True)
    except Exception as e:
        print("\n" + "=" * 50, flush=True)
        print("ОШИБКА:", flush=True)
        print("=" * 50, flush=True)
        import traceback
        traceback.print_exc()
        print("=" * 50, flush=True)
    try:
        input("\nНажмите Enter, чтобы закрыть...")
    except (EOFError, KeyboardInterrupt):
        pass

if __name__ == "__main__":
    main()
