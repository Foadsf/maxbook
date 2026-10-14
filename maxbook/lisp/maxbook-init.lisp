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
;;;   HELLO  error-marker syntax-marker lisp-error-marker version lisp pid
;;;   PROMPT n            Maxima is ready to read input line n
;;;   ASK / ASKEND        bracket a question Maxima asks (asksign, read(), ...)
;;;   OUT label tex text semtex
;;;                       one displayed result; semtex is the same TeX with
;;;                       every symbol wrapped in \class{mbk-sym mbk-KIND mbk-n-HEX}
;;;   IMG path            an image file to embed (inline plots)
;;;   SYM json            the session's symbol table (answer to mbk-symbols)

(in-package :maxima)

;;; ------------------------------------------------------------ JSON helpers
(defun mbk-json-string (s)
  (with-output-to-string (out)
    (write-char #\" out)
    (loop for c across s
          for code = (char-code c)
          do (cond ((char= c #\") (write-string "\\\"" out))
                   ((char= c #\\) (write-string "\\\\" out))
                   ((< code 32) (format out "\\u~4,'0x" code))
                   (t (write-char c out))))
    (write-char #\" out)))

(defun mbk-json-object (pairs)
  "PAIRS is a list of (key . string-value); NIL values are written as null."
  (format nil "{~{~a~^,~}}"
          (mapcar (lambda (p)
                    (format nil "~a:~a" (mbk-json-string (car p))
                            (if (cdr p) (mbk-json-string (cdr p)) "null")))
                  pairs)))

;;; ------------------------------------------------------------ semantic TeX
;;; Maxima's TeX printer renders every symbol through TEX-ATOM.  While
;;; *MBK-TAG-SYMBOLS* is true we wrap user-visible symbols in \class{...} so
;;; the notebook can colour them and show what they are on hover.

(defvar *mbk-tag-symbols* nil)
(defvar *mbk-orig-tex-atom* (symbol-function 'tex-atom))
(defparameter *mbk-builtin-constants*
  '($%pi $%e $%i $%phi $%gamma $inf $minf $infinity $und $ind $zeroa $zerob))

(defun mbk-name (x) (print-invert-case (stripdollar x)))

(defun mbk-hex (s)
  (format nil "~{~4,'0x~}" (map 'list #'char-code s)))

;; Names Maxbook itself defines (maxbook.mac helpers and settings) are part of
;; the system, not the user's notebook: recorded once the session is set up.
(defvar *mbk-system-symbols* (make-hash-table :test #'eq))
(defun mbk-system-p (x) (gethash x *mbk-system-symbols*))

(defun mbk-symbol-kind (x)
  "constant, function, variable or free; NIL for built-in operators and keywords."
  (cond ((not (and (symbolp x) x (not (eq x t)))) nil)
        ((member x *mbk-builtin-constants*) "constant")
        ((handler-case (eq (mfuncall '$featurep x '$constant) t) (error () nil)) "constant")
        ((member x '($true $false $done $all $maxbook_graphics)) nil)
        ((mbk-system-p x) nil)
        ((mget x 'mexpr) "function")
        ((and (boundp x) (member x (cdr $values) :test #'eq)) "variable")
        ((or (fboundp x) (get x 'mfexpr*) (get x 'operators) (get x 'noun) (get x 'verb)
             (get x 'alias) (get x 'reversealias) (get x 'opr) (get x 'lbp)) nil)
        ((char/= (char (symbol-name x) 0) #\$) nil)
        (t "free")))

(defun tex-atom (x l r)
  (let ((kind (and *mbk-tag-symbols* (mbk-symbol-kind x))))
    (if kind
        (let ((inner (funcall *mbk-orig-tex-atom* x nil nil)))
          (append l
                  (list (format nil "\\class{mbk-sym mbk-~a mbk-n-~a}{~{~a~}}"
                                kind (mbk-hex (mbk-name x)) inner))
                  r))
        (funcall *mbk-orig-tex-atom* x l r))))

(defun mbk-tex (expr &optional tag)
  (handler-case (let (($display2d nil) (*mbk-tag-symbols* tag)) (mfuncall '$tex1 expr))
    (error () nil)))

(defun mbk-text (expr)
  (handler-case (let (($display2d nil)) (coerce (mstring expr) 'string))
    (error () nil)))

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
      (mbk-emit "OUT"
                (if label (print-invert-case (stripdollar label)) "")
                (or (mbk-tex expr) "")
                (or (mbk-text expr) "")
                (or (mbk-tex expr t) "")))))

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

;;; ------------------------------------------------------------ symbol table
(defun mbk-clip (s n) (if (and s (> (length s) n)) (concatenate 'string (subseq s 0 n) "…") s))

(defun mbk-symbol-entry (kind name tex text)
  (mbk-json-object (list (cons "kind" kind) (cons "name" name)
                         (cons "latex" (and tex (<= (length tex) 4000) tex))
                         (cons "text" (mbk-clip text 600)))))

(defun mbk-mark-system ()
  (dolist (v (cdr $values)) (when (symbolp v) (setf (gethash v *mbk-system-symbols*) t)))
  (dolist (f (cdr $functions)) (when (consp f) (setf (gethash (caar f) *mbk-system-symbols*) t)))
  (values))

;; Names a file defines while it loads (a package such as eigen or draw,
;; often loaded automatically) belong to that library, not to the notebook.
;; Only names that are new after the load are marked, so the user's own
;; earlier definitions stay theirs.
(defun mbk-defined-names ()
  (append (remove-if-not #'symbolp (cdr $values))
          (mapcar #'caar (remove-if-not #'consp (cdr $functions)))))

(defun mbk-marking-new-names (fn args)
  (let ((before (mbk-defined-names)))
    (multiple-value-prog1 (apply fn args)
      (dolist (name (mbk-defined-names))
        (unless (member name before :test #'eq)
          (setf (gethash name *mbk-system-symbols*) t))))))

;; load("pkg") goes through $load; autoloaded functions go through ALOAD,
;; $ALOAD_MAC (auto_mexpr stubs such as eigenvalues -> eigen.mac) or
;; GENERIC-AUTOLOAD.
(dolist (fname '($load aload $aload_mac generic-autoload))
  (let ((orig (symbol-function fname)))
    (setf (symbol-function fname)
          (lambda (&rest args) (mbk-marking-new-names orig args)))))

(defun mbk-symbols ()
  "Emit a SYM frame describing user variables, user functions and declared constants."
  (let ((entries '()))
    (dolist (v (cdr $values))
      (when (and (symbolp v) (not (mbk-system-p v)))
        (handler-case
            (let ((val (symbol-value v)))
              (push (mbk-symbol-entry "variable" (mbk-name v) (mbk-tex val t) (mbk-text val)) entries))
          (error () nil))))
    (dolist (f (cdr $functions))
      (handler-case
          (let* ((fname (caar f))
                 (def (mget fname 'mexpr))
                 (form (and def `((mdefine) ((,fname) ,@(cdadr def)) ,(caddr def)))))
            (when (and form (not (mbk-system-p fname)))
              (push (mbk-symbol-entry "function" (mbk-name fname) (mbk-tex form t) (mbk-text form))
                    entries)))
        (error () nil)))
    (dolist (s (cdr $props))
      (when (and (symbolp s) (not (member s *mbk-builtin-constants*))
                 (handler-case (eq (mfuncall '$featurep s '$constant) t) (error () nil)))
        (push (mbk-symbol-entry "constant" (mbk-name s) nil nil) entries)))
    (mbk-emit "SYM" (format nil "[~{~a~^,~}]" (nreverse entries)))
    (values)))

(mbk-emit "HELLO"
          (string-trim '(#\Newline #\Space)
                       (format nil (intl:gettext "~& -- an error. To debug this try: debugmode(true);~%")))
          (string-trim '(#\Newline #\Space) (intl:gettext "incorrect syntax: "))
          (string-trim '(#\Newline #\Space)
                       (format nil (intl:gettext "~&Maxima encountered a Lisp error:~%~% ~A") ""))
          *autoconf-version*
          (lisp-implementation-type)
          (handler-case (getpid) (error () -1)))
