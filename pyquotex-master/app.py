import os
import sys
import asyncio
import datetime
import logging
import time
from telethon import TelegramClient, events
from quotexapi.stable_api import Quotex
from quotexapi.stable_api import asrun

# Configuración del logger
logging.basicConfig(
    filename='trading_bot.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Datos de inicio de sesión de Quotex
email = "lucatonny90@gmail.com"
password = "Acer1998*"
email_pass = None
user_data_dir = os.path.join(os.getcwd(), "user_data")

# Datos de Telegram
api_id = '23334305'
api_hash = '695c8ec0bd2a3f13a53bcd0028a110b4'
phone = '+573006240800'

# Parámetros de configuración
initial_amount = 1  # Monto inicial a invertir
max_retries = 2     # Número máximo de repeticiones (gales)

async def main():
    try:
        # Cliente de Telegram
        telegram_client = TelegramClient('session_name', api_id, api_hash)
        await telegram_client.start()

        # Obtener el canal de Telegram
        channel = await telegram_client.get_entity('https://t.me/+BgSI26oXfKs1MTNh')

        # Handler para nuevos mensajes
        @telegram_client.on(events.NewMessage(chats=channel))
        async def handler(event):
            message = event.message.message
            parsed_signal = parse_signal(message)
            if parsed_signal:
                asset, direction, scheduled_time_str, duration, timezone_offset = parsed_signal
                wait_time = calculate_wait_time(scheduled_time_str, timezone_offset)
                if wait_time >= 0:
                    logging.info(f"Operación programada en {wait_time} segundos para el activo {asset}.")
                    operation = {
                        'asset': asset,
                        'direction': direction,
                        'scheduled_time_str': scheduled_time_str,
                        'duration_minutes': duration,
                        'wait_time': wait_time
                    }
                    # Iniciar una nueva tarea para ejecutar la operación
                    asyncio.create_task(execute_trade(operation))
                    logging.info(f"Operación programada: {operation}")
                else:
                    logging.warning("La hora de la operación ya pasó. Señal ignorada.")
            else:
                logging.warning("No se pudo interpretar la señal correctamente.")

        logging.info("Escuchando mensajes en el canal de Telegram...")
        await telegram_client.run_until_disconnected()

    except Exception as e:
        logging.error(f"Ocurrió una excepción en main: {e}")

def parse_signal(message):
    try:
        # Lógica para extraer la señal del mensaje
        lines = message.strip().split('\n')
        asset, direction, scheduled_time_str, duration, timezone_offset = None, None, None, None, None

        for line in lines:
            line = line.strip()
            if 'Huso Horario' in line:
                timezone_offset = int(line.split('(UTC')[1].split(')')[0].split(':')[0])
            elif '•' in line and '-' in line:
                parts = line.replace('•', '').split('-')
                asset = parts[0].strip()
                direction = parts[1].split()[0].strip().lower()
            elif 'Operacion en:' in line:
                scheduled_time_str = line.split('Operacion en:')[1].strip()
            elif 'Caducidad:' in line:
                duration = int(line.split('Caducidad:')[1].strip().split('minutos')[0])

        if not all([asset, direction, scheduled_time_str, duration, timezone_offset]):
            logging.warning("Faltan datos en la señal. No se puede proceder.")
            return None

        return asset, direction, scheduled_time_str, duration, timezone_offset

    except Exception as e:
        logging.error(f"Error al analizar la señal: {e}")
        return None

def calculate_wait_time(scheduled_time_str, timezone_offset):
    try:
        operation_timezone = datetime.timezone(datetime.timedelta(hours=timezone_offset))
        now_operation_tz = datetime.datetime.now(tz=operation_timezone)
        today = now_operation_tz.date()
        operation_time = datetime.datetime.strptime(scheduled_time_str, '%H:%M').replace(
            year=today.year, month=today.month, day=today.day, tzinfo=operation_timezone)
        
        operation_time -= datetime.timedelta(seconds=5)

        wait_time = (operation_time - now_operation_tz).total_seconds()

        if wait_time < 0:
            operation_time += datetime.timedelta(days=1)
            wait_time = (operation_time - now_operation_tz).total_seconds()

        return wait_time

    except Exception as e:
        logging.error(f"Error al calcular el tiempo de espera: {e}")
        return -1

async def execute_trade(operation):
    try:
        asset = operation['asset']
        direction = operation['direction']
        scheduled_time_str = operation['scheduled_time_str']
        duration_minutes = operation['duration_minutes']
        wait_time = operation['wait_time']

        # Esperar hasta la hora programada
        await asyncio.sleep(wait_time)

        amount = initial_amount
        retries = 0
        duration = duration_minutes * 60
        max_retries_local = max_retries  # Usar una variable local para los reintentos

        # Generar un identificador único para la operación
        operation_id = f"{asset}_{scheduled_time_str}_{int(time.time())}"
        logging.info(f"Iniciando operación {operation_id}")

        # Crear una nueva instancia de Quotex para esta operación
        quotex_client = Quotex(
            email=email,
            password=password,
            email_pass=email_pass,
            user_data_dir=user_data_dir
        )

        check_connect, message = await quotex_client.connect()
        if not check_connect:
            logging.error(f"Error al conectar con Quotex: {message}")
            return

        quotex_client.change_account("DEMO")
        logging.info("Conexión exitosa con la cuenta DEMO de Quotex")

        while retries <= max_retries_local:
            logging.info(f"Operación {operation_id}, Intento {retries + 1}: Operando {asset} en dirección {direction.upper()} con monto {amount}.")
            if not quotex_client.check_connect():
                logging.warning("Conexión con Quotex no está activa. Intentando reconexión...")
                check_connect, message = await quotex_client.connect()
                if not check_connect:
                    logging.error(f"No se pudo reconectar con Quotex: {message}")
                    break
                quotex_client.change_account("DEMO")

            asset_name, asset_data = await quotex_client.get_available_asset(asset, force_open=True)
            if asset_data and asset_data[2]:
                status, buy_info = await quotex_client.buy(amount, asset_name, direction, duration)
                if status:
                    position_id = buy_info.get('id')
                    result = await wait_for_result(quotex_client, position_id)
                    if result == 'win':
                        logging.info(f"Operación {operation_id} ganada en el intento {retries + 1}.")
                        break
                    elif result == 'loss':
                        retries += 1
                        amount *= 3  # Multiplicar el monto según la estrategia de martingala
                        logging.warning(f"Operación {operation_id} perdida en el intento {retries}. Intentando nuevamente con monto {amount}.")
                    else:
                        logging.error(f"Resultado desconocido de la operación {operation_id}.")
                        break
                else:
                    logging.error(f"Operación {operation_id} fallida para {asset}. Estado negativo recibido.")
                    break
            else:
                logging.warning(f"El activo {asset} está cerrado o no disponible para la operación {operation_id}.")
                break

        # Cerrar la conexión de Quotex para esta operación
        quotex_client.close()

    except Exception as e:
        logging.error(f"Error al ejecutar la operación {operation_id}: {e}")

async def wait_for_result(quotex_client, position_id):
    try:
        result = await quotex_client.check_win(position_id)
        return 'win' if result is True else 'loss' if result is False else 'unknown'
    except Exception as e:
        logging.error(f"Error al obtener el resultado de la operación {position_id}: {e}")
        return 'unknown'

if __name__ == "__main__":
    try:
        asrun(main())
    except KeyboardInterrupt:
        logging.info("¡Operación abortada por el usuario!")
        sys.exit(0)