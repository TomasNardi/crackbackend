import asyncio

async def test1(params): 
    await session.get("AFIP")
    # print(f"Se usa el parametro {params}")
    # await asyncio.sleep(params)
    # return f'Finalizando la funcion 1'

async def test2(params): 
    await session.get("INSTAGRAM")
    # print(f"Se usa el parametro {params}")
    # await asyncio.sleep(params)
    # return f'Finalizando la funcion 2 '

async def main():
    prueba2 = asyncio.create_task(test2(2))
    prueba1 = asyncio.create_task(test1(1))
    
    resultado1 = await prueba1 
    resultado2 = await prueba2 

if __name__ == "__main__":
    asyncio.run(main())