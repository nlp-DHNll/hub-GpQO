import { expect, test } from "@playwright/test";
test("登录页展示产品与共享密码输入", async ({page})=>{await page.goto("/login");await expect(page.getByRole("heading",{name:"欢迎回来"})).toBeVisible();await expect(page.getByLabel("共享密码")).toBeVisible()});
