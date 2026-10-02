@echo off
REM ============================================================
REM  ComfyUI no Modal (T4) — liga e, ao fechar, DESLIGA sozinho
REM ============================================================
REM  Duplo-clique neste arquivo para abrir o ComfyUI de aprendizado.
REM  - Sobe o ComfyUI na T4 do Modal (comeca a faturar quando voce usa).
REM  - Mostra a URL para abrir no navegador.
REM  - Ao FECHAR esta janela (ou Ctrl+C), roda 'modal app stop'
REM    automaticamente para a T4 NAO ficar faturando parada.
REM ============================================================

cd /d "%~dp0"

set PY=C:\Python313\python.exe
set APP=comfyui-aprendizado

echo.
echo ============================================================
echo  Subindo ComfyUI na T4 do Modal...
echo  Quando aparecer a URL (…modal.run), abra no navegador.
echo.
echo  PARA ENCERRAR: feche esta janela ou aperte Ctrl+C.
echo  O desligamento da GPU e' automatico ao sair.
echo ============================================================
echo.

REM Sobe o ComfyUI. Fica rodando aqui ate voce fechar/Ctrl+C.
"%PY%" -m modal serve modal_app/comfyui.py

REM --- Quando o serve termina (voce fechou/Ctrl+C), desliga a T4 ---
echo.
echo ============================================================
echo  Encerrando: parando a app no Modal (desligar a GPU)...
echo ============================================================
"%PY%" -m modal app stop %APP%

echo.
echo  Pronto. GPU desligada. Pode fechar esta janela.
pause
