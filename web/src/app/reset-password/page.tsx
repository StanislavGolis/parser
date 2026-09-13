import type { Metadata } from "next";

import ResetPasswordForm from "@/components/ResetPasswordForm";

export const metadata: Metadata = { title: "Смена пароля" };

/** Страница из письма: смена пароля по одноразовой ссылке (её выдаёт админ). */
export default function ResetPasswordPage() {
  return (
    <div className="container-site max-w-md py-10">
      <ResetPasswordForm />
    </div>
  );
}
