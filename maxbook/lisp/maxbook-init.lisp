;;; SPDX-License-Identifier: GPL-3.0-or-later
;;; Copyright (C) 2026 Foad S. Farimani
;;; Maxbook <-> Maxima wire protocol.
;;;
;;; Loaded with `maxima --very-quiet -p maxbook-init.lisp`.  Everything the
;;; front end needs to parse is written as a frame:
;;;
;;;     STX KIND [US FIELD]... ETX
;;;
;;; with STX = U+0002, US = U+001F, ETX = U+0003.  Text outside frames is plain
;;; Maxima output (print statements, warnings, error messages).
;;;
;;;   HELLO  error-marker syntax-marker lisp-error-marker version lisp
;;;   PROMPT n            Maxima is ready to read input line n
;;;   ASK / ASKEND        bracket a question Maxima asks (asksign, read(), ...)
;;;   OUT label tex text  one displayed result
;;;   IMG path            an image file to embed (inline plots)

(in-package :maxima)

(defun mbk-frame (kind &rest fields)
  (with-output-to-string (s)
    (write-char (code-char 2) s)
    (write-string kind s)
    (dolist (f fields)
      (write-char (code-char 31) s)
      (write-string (if (stringp f) f (princ-to-string f)) s))
    (write-char (code-char 3) s)))

(defun mbk-emit (kind &rest fields)
  (finish-output)
  (write-string (apply #'mbk-frame kind fields))
  (terpri)
  (finish-output))

(defun mbk-display (form)
  (let* ((labelled (and (consp form) (consp (car form)) (eq (caar form) 'mlabel)))
         (label (if labelled (cadr form) nil))
         (expr (if labelled (caddr form) form)))
    ;; Inline graphics functions return this marker; the IMG frame already
    ;; carries the result, so there is nothing to display.
    (unless (eq expr '$maxbook_graphics)
      (let ((tex (handler-case (let (($display2d nil)) (mfuncall '$tex1 expr))
                   (error () nil)))
            (lin (handler-case (let (($display2d nil)) (coerce (mstring expr) 'string))
                   (error () nil))))
        (mbk-emit "OUT"
                  (if label (print-invert-case (stripdollar label)) "")
                  (or tex "")
                  (or lin ""))))))

(setq *alt-display2d* #'mbk-display)
(setq *alt-display1d* #'mbk-display)

;; The main prompt marks "ready for the next statement".  Questions go through
;; FORMAT-PROMPT, which wraps them in *prompt-prefix* / *prompt-suffix*.
(defun main-prompt ()
  (mbk-frame "PROMPT" (format nil "~d" $linenum)))

(setq *prompt-prefix* (mbk-frame "ASK"))
(setq *prompt-suffix* (mbk-frame "ASKEND"))

;; Load a package without its compiler chatter (";; Note: ..."), which some
;; Lisps print while loading share packages such as draw.  If loading fails,
;; the captured output is shown so the error stays explainable.
(defmfun $maxbook_quiet_load (file)
  (let ((captured (make-string-output-stream))
        (ok nil))
    (unwind-protect
         (prog1 (let ((*standard-output* captured)
                      (*error-output* captured))
                  ($load file))
           (setq ok t))
      (unless ok
        (write-string (get-output-stream-string captured))
        (finish-output)))))

(defmfun $maxbook_show_image (file)
  (unless (stringp file)
    (merror "maxbook_show_image: expected a file name string, got ~M" file))
  (mbk-emit "IMG" file)
  '$maxbook_graphics)

(mbk-emit "HELLO"
          (string-trim '(#\Newline #\Space)
                       (format nil (intl:gettext "~& -- an error. To debug this try: debugmode(true);~%")))
          (string-trim '(#\Newline #\Space) (intl:gettext "incorrect syntax: "))
          (string-trim '(#\Newline #\Space)
                       (format nil (intl:gettext "~&Maxima encountered a Lisp error:~%~% ~A") ""))
          *autoconf-version*
          (lisp-implementation-type))
