import os
import sys
import asyncio
import datetime
from telethon import TelegramClient, events
from quotexapi.stable_api import Quotex
from quotexapi.stable_api import asrun

import os
import asyncio
import datetime
from telethon import TelegramClient, events
from quotexapi.stable_api import Quotex

import quotexapi.stable_api


# Datos de inicio de sesión de Quotex
email = ""
password = ""
email_pass = None
user_data_dir = os.path.join(os.getcwd(), "user_data")

# Datos de Telegram
api_id = ''
api_hash = ''
phone = ''

# Parámetros de configuración
initial_amount = 1  # Monto inicial a invertir
max_retries = 2     # Número máximo de repeticiones (gales)

async def main():
    try:
        # Cliente de Quotex
        quotex_client = Quotex(
            email=email,
            password=password,
            email_pass=email_pass,
            user_data_dir=user_data_dir
        )

        check_connect, message = await quotex_client.connect()
        if not check_connect:
            print("Error al conectar con Quotex:", message)
            return

        quotex_client.change_account("DEMO")

        # Cliente de Telegram
        telegram_client = TelegramClient('session_name', api_id, api_hash)
        await telegram_client.start()

        # Obtener el canal de Telegram
        channel = await telegram_client.get_entity('link')

        # Handler para nuevos mensajes
        @telegram_client.on(events.NewMessage(chats=channel))
        async def handler(event):
            message = event.message.message
            asset, direction, scheduled_time_str, duration, timezone_offset = parse_signal(message)
            if asset and direction and scheduled_time_str and duration and timezone_offset is not None:
                wait_time = calculate_wait_time(scheduled_time_str, timezone_offset)
                if wait_time > 0:
                    print(f"Operación programada en {wait_time} segundos.")
                    # Crear una nueva tarea para la operación
                    asyncio.create_task(schedule_and_execute_trade(quotex_client, asset, direction, scheduled_time_str, duration, wait_time))
                else:
                    print("La hora de la operación ya pasó.")
            else:
                print("No se pudo interpretar la señal.")

        async def schedule_and_execute_trade(quotex_client, asset, direction, scheduled_time_str, duration, wait_time):
            await asyncio.sleep(wait_time)
            await execute_trade(quotex_client, asset, direction, scheduled_time_str, duration)

        print("Escuchando mensajes...")
        await telegram_client.run_until_disconnected()

    except Exception as e:
        print(f"Ocurrió una excepción en main: {e}")
    finally:
        # Cerrar el cliente de Quotex al finalizar
        quotex_client.close()

async def ensure_connected(quotex_client):
    if not quotex_client.check_connect():
        print("Conexión con Quotex no está activa. Reinicializando el cliente...")
        # Cerrar la conexión existente
        quotex_client.close()
        # Crear una nueva instancia del cliente de Quotex
        new_quotex_client = Quotex(
            email=email,
            password=password,
            email_pass=email_pass,
            user_data_dir=user_data_dir
        )
        check_connect, message = await new_quotex_client.connect()
        if check_connect:
            print("Reconexión exitosa.")
            # Cambiar a cuenta DEMO si es necesario
            new_quotex_client.change_account("DEMO")
            return new_quotex_client
        else:
            print("No se pudo reconectar con Quotex:", message)
            return None
    return quotex_client

def parse_signal(message):
    # Dividir el mensaje por líneas
    lines = message.strip().split('\n')
    
    # Inicializar variables
    asset = None
    direction = None
    scheduled_time_str = None  # Hora programada como cadena
    duration = None  # Duración en minutos
    timezone_offset = None  # En horas, por ejemplo, -3 para UTC-3
    
    for line in lines:
        line = line.strip()
        if 'Huso Horario' in line:
            # Extraer la zona horaria
            try:
                timezone_str = line.split('(UTC')[1].split(')')[0]
                timezone_offset = int(timezone_str.split(':')[0])
            except Exception as e:
                timezone_offset = -3  # Por defecto UTC-3
        elif '•' in line and '-' in line:
            # Extraer activo y dirección
            try:
                parts = line.replace('•', '').split('-')
                if len(parts) >= 2:
                    asset = parts[0].strip()
                    direction = parts[1].split()[0].strip().lower()
            except Exception as e:
                pass
        elif 'Operacion en:' in line:
            # Extraer la hora de ejecución
            try:
                scheduled_time_str = line.split('Operacion en:')[1].strip()
            except Exception as e:
                pass
        elif 'Caducidad:' in line:
            # Extraer la duración
            try:
                duration_part = line.split('Caducidad:')[1].strip()
                if 'minutos' in duration_part:
                    duration = int(duration_part.split('minutos')[0].strip())
                elif 'M' in duration_part:
                    duration = int(duration_part.split('M')[0].strip())
            except Exception as e:
                pass

    return asset, direction, scheduled_time_str, duration, timezone_offset

def calculate_wait_time(scheduled_time_str, timezone_offset):
    # Crear un objeto timezone para la zona horaria de la operación
    operation_timezone = datetime.timezone(datetime.timedelta(hours=timezone_offset))

    # Obtener la hora actual en la zona horaria de la operación
    now_operation_tz = datetime.datetime.now(tz=operation_timezone)

    # Crear un objeto datetime para la hora de ejecución en la zona horaria de la operación
    today = now_operation_tz.date()
    operation_time = datetime.datetime.strptime(scheduled_time_str, '%H:%M').replace(
        year=today.year, month=today.month, day=today.day, tzinfo=operation_timezone)

    # Calcular el tiempo de espera en segundos
    wait_time = (operation_time - now_operation_tz).total_seconds()

    # Si el tiempo de espera es negativo, considerar el día siguiente
    if wait_time < 0:
        operation_time += datetime.timedelta(days=1)
        wait_time = (operation_time - now_operation_tz).total_seconds()

    return wait_time

async def execute_trade(quotex_client, asset, direction, scheduled_time_str, duration_minutes):
    amount = initial_amount
    retries = 0

    # Convertir la duración del mensaje (en minutos) a segundos
    duration = duration_minutes * 60  # Duración en segundos (ej. M1 -> 60 segundos)

    # Imprimir la duración calculada para depuración
    print(f"Duración de la operación especificada: {duration} segundos")

    while retries <= max_retries:
        print(f"Intento {retries + 1}: Operando {asset} en dirección {direction.upper()} con monto {amount}.")

        # Verificar y asegurar conexión
        quotex_client = await ensure_connected(quotex_client)
        if not quotex_client:
            print("No se pudo establecer conexión con Quotex. Abortando operación.")
            break

        if duration <= 0:
            print("La duración especificada es inválida. Abortando operación.")
            break

        asset_name, asset_data = await quotex_client.get_available_asset(asset, force_open=True)
        if asset_data[2]:
            try:
                status, buy_info = await quotex_client.buy(amount, asset_name, direction, duration)
                print(f"Resultado de la compra: status={status}, buy_info={buy_info}")
            except Exception as e:
                print(f"Error al realizar la operación de compra: {e}")
                import traceback
                traceback.print_exc()
                if 'Connection is already closed' in str(e):
                    print("Intentando reconectar con Quotex...")
                    quotex_client = await ensure_connected(quotex_client)
                    if quotex_client:
                        print("Reconexión exitosa. Intentando comprar de nuevo...")
                        # Reintentar la compra inmediatamente
                        try:
                            # Actualizar asset_name y asset_data si es necesario
                            asset_name, asset_data = await quotex_client.get_available_asset(asset, force_open=True)
                            if asset_data[2]:
                                status, buy_info = await quotex_client.buy(amount, asset_name, direction, duration)
                                print(f"Resultado de la compra: status={status}, buy_info={buy_info}")
                            else:
                                print(f"El activo {asset} está cerrado después de reconexión.")
                                break
                        except Exception as e:
                            print(f"Error al realizar la operación de compra después de reconexión: {e}")
                            break  # O manejar según corresponda
                    else:
                        print("No se pudo reconectar con Quotex. Abortando operación.")
                        break
                else:
                    print("Error desconocido. Abortando operación.")
                    break

            if status:
                if not buy_info:
                    print("No se pudo obtener la información de la compra, `buy_info` es `None`.")
                    break

                position_id = buy_info.get('id')
                if not position_id:
                    print("No se pudo obtener el ID de la posición.")
                    break

                print(f"Esperando resultado de la operación para el ID {position_id}...")
                result = await wait_for_result(quotex_client, position_id)
                print(f"Resultado de la operación: {result}")

                if result == 'win':
                    print(f"Operación {position_id} ganada.")
                    break  # Finalizar el proceso si la operación fue ganada
                elif result == 'loss':
                    print(f"Operación {position_id} perdida.")
                    retries += 1
                    if retries > max_retries:
                        print("Se alcanzó el número máximo de repeticiones.")
                        break
                    else:
                        amount *= 3  # Multiplica el monto por 3 según Martingala
                        print(f"Realizando nueva operación de recuperación con monto {amount}...")
                else:
                    print(f"No se pudo determinar el resultado de la operación {position_id}.")
                    break
            else:
                print(f"Error al realizar la operación {asset}. Estado negativo recibido.")
                break
        else:
            print(f"El activo {asset} está cerrado.")
            break

async def wait_for_result(quotex_client, position_id):
    try:
        print(f"Esperando resultado de la operación para el ID {position_id}...")
        result = await quotex_client.check_win(position_id)
        print(f"Resultado de la operación {position_id}: {result}, tipo: {type(result)}")
        if result is True:
            return 'win'
        elif result is False:
            return 'loss'
        else:
            print("Resultado desconocido de la operación.")
            return 'unknown'
    except Exception as e:
        print(f"Error al obtener el resultado de la operación: {e}")
        return 'unknown'


if __name__ == "__main__":
    try:
        asrun(main())
    except KeyboardInterrupt:
        print("¡Operación abortada por el usuario!")
        sys.exit(0)
