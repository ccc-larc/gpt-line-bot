import logging
import time

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from openai import NotFoundError, OpenAI

from gpt_line_bot.models import UserThread

logger = logging.getLogger(__name__)

handler = WebhookHandler(settings.LINE_CHANNEL_SECRET)

configuration = Configuration(access_token=settings.LINE_CHANNEL_ACCESS_TOKEN)

openai_client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    organization=settings.OPENAI_ORGANIZATION_ID,
    project=settings.OPENAI_PROJECT_ID,
)


@csrf_exempt
@require_POST
def line_bot_webhook(request):
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.body.decode()
    logger.info('Request body: ' + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        error_message = 'Invalid signature. Please check your channel access token/channel secret.'
        logger.error(error_message)
        return HttpResponseBadRequest(error_message)

    return HttpResponse('OK')


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    line_user_id = event.source.user_id
    content = event.message.text

    logger.info(f'LINE user [{line_user_id}]: {content}')

    answer = ask_openai_assistant(line_user_id=line_user_id, content=content)

    logger.info(f'OpenAI answer: {answer}')

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=answer)]
            )
        )


def ask_openai_assistant(line_user_id: str, content: str) -> str:
    thread_id = get_or_create_openai_thread_id(line_user_id)

    openai_client.beta.threads.messages.create(
        thread_id,
        role='user',
        content=content,
    )

    status = create_run_and_wait_completed(thread_id)
    if status != 'completed':
        return '很抱歉，我在尋找答案時遇到了錯誤，或許您可以換個方式再問一次。'

    messages = openai_client.beta.threads.messages.list(thread_id)

    logger.info(f'OpenAI messages: {messages}')

    msg = messages.data[0]
    content = msg.content[0]
    if content.type == 'text':
        return content.text.value
    else:
        return '很抱歉，我在處理回應時遇到了錯誤，或許您可以換個方式再問一次。'


def get_or_create_openai_thread_id(line_user_id: str):
    user_thread = UserThread.objects.filter(line_user_id=line_user_id).first()
    if user_thread:
        try:
            thread = openai_client.beta.threads.retrieve(user_thread.openai_thread_id)
            logger.info(f'Use existed OpenAI thread: {thread}')
            return thread.id
        except NotFoundError:
            UserThread.objects.filter(id=user_thread.id).delete()

    thread = openai_client.beta.threads.create()
    UserThread.objects.create(
        line_user_id=line_user_id,
        openai_thread_id=thread.id,
    )
    logger.info(f'Create new OpenAI thread: {thread}')
    return thread.id


def create_run_and_wait_completed(thread_id: str) -> str:
    assistant_run = openai_client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=settings.OPENAI_ASSISTANT_ID,
    )

    status = assistant_run.status

    while status != 'completed':
        logger.info(f'OpenAI run status: {status}')

        if status == 'queued':
            wait_seconds = 5
        elif status == 'failed':
            break
        else:
            wait_seconds = 3

        time.sleep(wait_seconds)

        run = openai_client.beta.threads.runs.retrieve(
            thread_id=thread_id,
            run_id=assistant_run.id,
        )
        status = run.status

    return status
