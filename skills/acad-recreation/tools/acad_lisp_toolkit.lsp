;;; ============================================================================
;;; acad_lisp_toolkit.lsp  —  <организация> toolkit для autocad-mcp recreation
;;; Загрузка: APPLOAD этого файла, либо (load "C:/.../acad_lisp_toolkit.lsp")
;;; Состав:
;;;   1) Динамические блоки — функции Lee Mac (lee-mac.com, свободно с атрибуцией)
;;;   2) ORG:* обёртки — безопасный блок, слои, вставка воздуховода
;;;   3) ORG:blocklist — стоп-слова для проверки опасного кода ПЕРЕД execute_lisp
;;; Тест: APPLOAD без ошибок + (ORG:dump-dynprops <ename блока эталона>)
;;; ============================================================================

;;; ----------------------------------------------------------------------------
;;; 1. ДИНАМИЧЕСКИЕ БЛОКИ — Lee Mac (canonical, lee-mac.com)
;;; ----------------------------------------------------------------------------

;; Список всех динамических свойств: ((name . value) ...)
(defun LM:getdynprops ( blk / lst )
    (foreach prop (vlax-invoke blk 'getdynamicblockproperties)
        (setq lst (cons (cons (vla-get-propertyname prop)
                              (vlax-get prop 'value))
                        lst)))
    (reverse lst))

;; Прочитать значение одного dyn-свойства по имени (nil если нет)
(defun LM:getdynpropvalue ( blk prop / result )
    (setq prop (strcase prop))
    (vl-some
        '(lambda ( p )
            (if (= prop (strcase (vla-get-propertyname p)))
                (setq result (vlax-get p 'value))))
        (vlax-invoke blk 'getdynamicblockproperties))
    result)

;; Установить значение одного dyn-свойства (T при успехе)
(defun LM:setdynpropvalue ( blk prop val )
    (setq prop (strcase prop))
    (vl-some
        '(lambda ( p )
            (if (= prop (strcase (vla-get-propertyname p)))
                (progn
                    (vla-put-value p (vlax-make-variant val
                        (vlax-variant-type (vla-get-value p))))
                    (cond ((vla-get-value p)) (t)))))
        (vlax-invoke blk 'getdynamicblockproperties)))

;; Текущее состояние видимости (visibility state), либо nil
(defun LM:getvisibilitystate ( blk / vis )
    (if (setq vis (LM:getvisibilityparametername blk))
        (LM:getdynpropvalue blk vis)))

;; Установить состояние видимости
(defun LM:setvisibilitystate ( blk val / vis )
    (if (setq vis (LM:getvisibilityparametername blk))
        (LM:setdynpropvalue blk vis val)))

;; Имя параметра видимости блока (если есть)
(defun LM:getvisibilityparametername ( blk / result )
    (if
        (and
            (vlax-property-available-p blk 'effectivename)
            (setq blk
                (vla-item
                    (vla-get-blocks (vla-get-document blk))
                    (vla-get-effectivename blk)))
            (= :vlax-true (vla-get-isdynamicblock blk))
            (= :vlax-true (vla-get-hasextensiondictionary blk)))
        (vl-some
            '(lambda ( pair )
                (if (= 360 (car pair))
                    (vl-some
                        '(lambda ( x )
                            (if (= "BlockVisibilityParameter" (cdr (assoc 0 (entget (cdr x)))))
                                (setq result (cdr (assoc 301 (entget (cdr x)))))))
                        (dictsearch (cdr pair) "ACAD_ENHANCEDBLOCK"))))
            (entget (vlax-vla-object->ename blk)))) ; обращение к словарю
    result)

;;; ----------------------------------------------------------------------------
;;; 2. ORG:* ОБЁРТКИ
;;; ----------------------------------------------------------------------------

;; Безопасный блок: весь шаг в одной UNDO-группе + финальный ZOOM E.
;; expr — список выражений (квотированный): (ORG:safe-run '((expr1)(expr2)...))
(defun ORG:safe-run ( exprs / )
    (vl-catch-all-apply
        '(lambda ()
            (command "_.UNDO" "_GROUP")
            (foreach e exprs (eval e))
            (command "_.UNDO" "_END")
            (command "_.ZOOM" "_E")))
    (princ))

;; Создать/настроить слои: ((name color-aci) ...). Continuous, по умолчанию печатается.
(defun ORG:ensure-layers ( specs / lyrs nm col )
    (setq lyrs (vla-get-layers
                 (vla-get-activedocument (vlax-get-acad-object))))
    (foreach s specs
        (setq nm (car s) col (cadr s))
        (if (not (tblsearch "LAYER" nm))
            (vla-add lyrs nm))
        (if col (vla-put-color (vla-item lyrs nm) col)))
    (princ))

;; Вставить динблок воздуховода: точка ins '(x y), диаметр D (мм), длина L (мм),
;; угол A (РАДИАНЫ), слой LYR. Параметры через dyn-props НАПРЯМУЮ (не lookup).
;; Возвращает vla-объект вставки.
(defun ORG:place-duct ( ins D L A lyr / doc ms blkref )
    (setq doc (vla-get-activedocument (vlax-get-acad-object))
          ms  (vla-get-modelspace doc))
    (setvar "CLAYER" lyr)                       ; слой ДО вставки
    (setq blkref (vla-insertblock ms
                   (vlax-3d-point (car ins) (cadr ins) 0.0)
                   "Воздуховод" 1.0 1.0 1.0 A)) ; кириллица ПРЯМО в коде
    (LM:setdynpropvalue blkref "Диаметр воздуховода" (vlax-make-variant D vlax-vbdouble))
    (LM:setdynpropvalue blkref "Радиус"              (vlax-make-variant (/ D 2.0) vlax-vbdouble))
    (LM:setdynpropvalue blkref "Расстояние1"         (vlax-make-variant L vlax-vbdouble))
    blkref)

;; Дамп dyn-свойств блока по ename — для разведки эталона (пишет в файл cp1251-safe)
(defun ORG:dump-dynprops ( ename path / blk f )
    (setq blk (vlax-ename->vla-object ename))
    (setq f (open path "w"))
    (foreach pr (LM:getdynprops blk)
        (write-line (strcat (car pr) " = " (vl-princ-to-string (cdr pr))) f))
    (close f)
    (princ (strcat "dumped -> " path)))

;;; ----------------------------------------------------------------------------
;;; 3. SAFETY-БЛОКЛИСТ — проверка ПЕРЕД execute_lisp (на стороне модели/оркестратора)
;;; ----------------------------------------------------------------------------
;; Стоп-слова: если присутствуют в генерируемом LISP — НЕ исполнять, спросить человека.
;; (Проверку делает оркестратор/скилл ДО отправки кода в execute_lisp.)
(setq ORG:blocklist
    '("wblock" "shell" "startapp" "vl-registry-write" "vl-registry-delete"
      "vl-file-delete" "vl-mkdir" "quit" "exit" "command \"_.erase\" \"_all\""))
;; Эвристика на стороне Python/оркестратора: lower(code) не должен содержать ни одного.

(princ "\nORG acad_lisp_toolkit загружен: LM:* (dynblocks) + ORG:* (safe-run/ensure-layers/place-duct/dump-dynprops).")
(princ)
;;; EOF
